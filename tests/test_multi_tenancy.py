# tests/test_multi_tenancy.py
#
# Cross-org isolation suite for Epoch 10 — starts here (PR 6/16, see
# ROADMAP.md's EPOCH 10 section). Each Epoch 10 PR that org-threads a new
# route/service adds its own isolation tests here rather than scattering
# them across the feature-specific test files.

import hashlib
import hmac
import io
import json
import uuid

import pytest

from app.core.exceptions import ProductSkuNotFoundError
from app.models.organization import Organization
from app.services.fleet_service import get_fleet_status
from app.services.product_service import get_product_by_sku

from .utils import create_product, purchase

_ORG1_WEBHOOK_SECRET = "org1-webhook-secret"  # noqa: S105 -- test fixture value, not a real credential
_ORG2_WEBHOOK_SECRET = "org2-webhook-secret"  # noqa: S105 -- test fixture value, not a real credential


def _set_webhook_secret(db, organization_id, secret):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org.webhook_secret = secret
    db.commit()


def _signed_webhook_request(client, organization_id, payload, secret):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        f"/api/webhooks/{organization_id}/ingest",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )


def _create_supplier(client, name="Acme Foods"):
    response = client.post("/api/suppliers", json={"name": name})
    assert response.status_code == 201, response.json()
    return response.json()


def _create_draft_po(client, supplier_id, product_id, quantity=10):
    response = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _recipe_item(client, finished_product_id, component_product_id, quantity):
    return client.post(
        "/api/recipes",
        json={
            "finished_product_id": finished_product_id,
            "component_product_id": component_product_id,
            "quantity": quantity,
        },
    )


def test_cross_org_inventory_level_returns_404(client, client_org2):
    """
    Epoch 10 PR 6 (inventory_service.py org threading): a user in org 2
    can't read org 1's product's inventory level by guessing its
    product_id — get_inventory() now requires the product to belong to
    the caller's own org.
    """
    org1_product = create_product(client)

    response = client_org2.get(f"/api/inventory/{org1_product['id']}")

    assert response.status_code == 404


def test_cross_org_create_event_returns_404(client, client_org2):
    """A user in org 2 can't record an inventory event against org 1's product."""
    org1_product = create_product(client)

    response = client_org2.post(
        "/api/inventory/events",
        json={
            "product_id": org1_product["id"],
            "event_type": "PURCHASE",
            "quantity": 10,
            "event_id": "cross-org-attempt",
        },
    )

    assert response.status_code == 404


def test_cross_org_get_events_returns_empty(client, client_org2):
    """
    A user in org 2 querying org 1's product's event history sees an
    empty list, not org 1's events — same "no such thing here" shape as
    querying an unknown product_id, not a 404 (this route never checked
    product existence, only ever filtered events).
    """
    org1_product = create_product(client)
    client.post(
        "/api/inventory/events",
        json={
            "product_id": org1_product["id"],
            "event_type": "PURCHASE",
            "quantity": 10,
            "event_id": "org1-only-event",
        },
    )

    response = client_org2.get(f"/api/inventory/events/{org1_product['id']}")

    assert response.status_code == 200
    assert response.json() == []


def test_create_product_same_sku_different_orgs_both_succeed(client, client_org2):
    """
    Epoch 10 PR 7 (product_service.py org threading, #143): products.sku
    became UNIQUE(organization_id, sku) back in PR 6 (#142), but
    create_product() didn't thread organization_id through until now —
    every product created via the API landed in org 1 regardless of which
    org's client made the request (see test_idempotency.py's
    test_same_event_id_different_orgs_both_succeed, which had to build its
    org-2 product directly via the ORM for exactly this reason). This
    proves the service layer now actually honors the caller's org.
    """
    payload = {"name": "Widget", "sku": "shared-sku-both-orgs"}

    r1 = client.post("/api/products", json=payload)
    assert r1.status_code == 201

    r2 = client_org2.post("/api/products", json=payload)
    assert r2.status_code == 201

    assert r1.json()["id"] != r2.json()["id"]


def test_get_product_by_sku_is_org_scoped(client, client_org2, db, second_org):
    """
    Epoch 10 PR 7 (#143): get_product_by_sku() now requires the caller's
    organization_id — org 1 querying a sku that only exists in org 2
    (even the identical sku string) must not find it, and vice versa.
    Not exposed over HTTP (only used internally by ingestion_service.py,
    which isn't org-threaded until #144), so this calls the service
    function directly against the shared `db` fixture session.
    """
    client.post("/api/products", json={"name": "Org1 Widget", "sku": "shared-sku"})
    client_org2.post("/api/products", json={"name": "Org2 Widget", "sku": "shared-sku"})

    org1_product = get_product_by_sku(db, "shared-sku", organization_id=1)
    org2_product = get_product_by_sku(db, "shared-sku", organization_id=second_org.id)

    assert org1_product.id != org2_product.id
    assert org1_product.organization_id == 1
    assert org2_product.organization_id == second_org.id

    with pytest.raises(ProductSkuNotFoundError):
        get_product_by_sku(db, "shared-sku", organization_id=second_org.id + 999)


def test_bulk_import_cross_org_sku_fails_cleanly(client, client_org2):
    """
    Epoch 10 PR 8 (ingestion_service.py org threading, #144): a CSV
    uploaded by org 1 that references org 2's sku by string alone must
    fail that row cleanly (product not found), not resolve cross-org —
    even though the sku string is real and exists, just in the wrong org.
    """
    org1_product = create_product(client, "Org1 Widget")
    org2_product = create_product(client_org2, "Org2 Widget")

    csv_content = (
        "sku,event_type,quantity,event_id\n"
        f"{org1_product['sku']},PURCHASE,10,evt-{uuid.uuid4()}\n"
        f"{org2_product['sku']},PURCHASE,10,evt-{uuid.uuid4()}\n"
    )
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 1
    assert body["results"][1]["status"] == "failed"
    assert org2_product["sku"] in body["results"][1]["error"]


def test_cross_org_update_recipe_item_returns_404(client, client_org2):
    """
    Epoch 10 PR 9 (recipe_service.py org threading + IDOR fix, #145):
    update_recipe_item_quantity() previously did a bare
    RecipeItem.id == id lookup with zero ownership check — a user in org
    2 who knows (or guesses) org 1's recipe_item_id must get a plain 404,
    not a 403 or a success, and org 1's quantity must be unchanged.
    """
    dish = create_product(client, "Burger")
    bun = create_product(client, "Bun")
    org1_item = _recipe_item(client, dish["id"], bun["id"], 1).json()

    response = client_org2.patch(f"/api/recipes/{org1_item['id']}", json={"quantity": 99})

    assert response.status_code == 404
    unchanged = client.get(f"/api/recipes/{dish['id']}").json()
    assert unchanged[0]["quantity"] == 1


def test_cross_org_delete_recipe_item_returns_404(client, client_org2):
    """Sibling to the update case above, for delete_recipe_item()."""
    dish = create_product(client, "Burger")
    bun = create_product(client, "Bun")
    org1_item = _recipe_item(client, dish["id"], bun["id"], 1).json()

    response = client_org2.delete(f"/api/recipes/{org1_item['id']}")

    assert response.status_code == 404
    still_there = client.get(f"/api/recipes/{dish['id']}").json()
    assert len(still_there) == 1


def test_supplier_list_and_create_scoped_per_org(client, client_org2):
    """
    Epoch 10 PR 10 (supplier_service.py org threading, #146): creating a
    supplier as org 2 must not land in org 1, and each org's list only
    ever shows its own suppliers.
    """
    org1_supplier = _create_supplier(client, "Org1 Supplier")
    org2_supplier = _create_supplier(client_org2, "Org2 Supplier")

    org1_names = {s["name"] for s in client.get("/api/suppliers").json()}
    org2_names = {s["name"] for s in client_org2.get("/api/suppliers").json()}

    assert org1_supplier["name"] in org1_names
    assert org2_supplier["name"] not in org1_names
    assert org2_supplier["name"] in org2_names
    assert org1_supplier["name"] not in org2_names


def test_cross_org_get_purchase_order_returns_404(client, client_org2):
    """
    Epoch 10 PR 10 (purchase_order_service.py org threading + IDOR fix,
    #146): get_purchase_order() previously did a bare
    PurchaseOrder.id == id lookup with zero ownership check — org 2
    guessing org 1's known purchase_order_id must get a plain 404.
    """
    org1_supplier = _create_supplier(client, "Org1 Supplier")
    org1_product = create_product(client, "Org1 Widget")
    org1_po = _create_draft_po(client, org1_supplier["id"], org1_product["id"])

    response = client_org2.get(f"/api/purchase-orders/{org1_po['id']}")

    assert response.status_code == 404


def test_cross_org_remove_purchase_order_line_returns_404(client, client_org2):
    """Sibling IDOR case for remove_purchase_order_line()."""
    org1_supplier = _create_supplier(client, "Org1 Supplier")
    org1_product = create_product(client, "Org1 Widget")
    org1_po = _create_draft_po(client, org1_supplier["id"], org1_product["id"])
    line_id = org1_po["lines"][0]["id"]

    response = client_org2.delete(f"/api/purchase-orders/lines/{line_id}")

    assert response.status_code == 404
    still_there = client.get(f"/api/purchase-orders/{org1_po['id']}").json()
    assert len(still_there["lines"]) == 1


def test_cross_org_submit_purchase_order_returns_404(client, client_org2):
    """Sibling IDOR case for submit_purchase_order()."""
    org1_supplier = _create_supplier(client, "Org1 Supplier")
    org1_product = create_product(client, "Org1 Widget")
    org1_po = _create_draft_po(client, org1_supplier["id"], org1_product["id"])

    response = client_org2.post(f"/api/purchase-orders/{org1_po['id']}/submit")

    assert response.status_code == 404
    unchanged = client.get(f"/api/purchase-orders/{org1_po['id']}").json()
    assert unchanged["status"] == "DRAFT"


def test_replay_does_not_touch_other_orgs_inventory_state(admin_client, admin_client_org2):
    """
    Epoch 10 PR 11 (replay_service.py real bug fix, #147):
    rebuild_inventory_state() used to do an unfiltered
    db.query(InventoryState).delete() before rebuilding — org 1's admin
    running replay wiped every org's projection, not just org 1's. This
    proves org 2's inventory level survives org 1 running replay
    untouched.
    """
    org2_product = create_product(admin_client_org2, "Org2 Widget")
    purchase(admin_client_org2, org2_product["id"], 30)

    before = admin_client_org2.get(f"/api/inventory/{org2_product['id']}").json()["quantity"]
    assert before == 30

    replay_response = admin_client.post("/api/inventory/replay")
    assert replay_response.status_code == 200

    after = admin_client_org2.get(f"/api/inventory/{org2_product['id']}").json()["quantity"]
    assert after == 30


def test_cross_org_restock_returns_404(client, client_org2):
    """
    Epoch 10 PR 11 (restock_service.py org threading, #147):
    get_restock_recommendation()'s inventory lookup is now org-scoped —
    org 1 querying org 2's product_id for a restock recommendation must
    get a plain 404 (product not found), not a stale/wrong-org result.
    """
    org2_product = create_product(client_org2, "Org2 Widget")

    response = client.get(f"/api/forecast/restock/{org2_product['id']}")

    assert response.status_code == 404


def test_fleet_status_scoped_per_org(client, client_org2, db, second_org):
    """
    Epoch 10 PR 11 (fleet_service.py org threading, #147):
    get_fleet_status() previously queried every product across every org
    with no filter at all — a straightforward cross-org data leak on the
    Fleet Overview dashboard page. Not exposed over HTTP (dashboard-only),
    so this calls the service function directly against the shared `db`
    fixture session.
    """
    org1_product = create_product(client, "Org1 Widget")
    org2_product = create_product(client_org2, "Org2 Widget")

    org1_fleet = get_fleet_status(db, organization_id=1)
    org2_fleet = get_fleet_status(db, organization_id=second_org.id)

    org1_skus = {p["sku"] for p in org1_fleet}
    org2_skus = {p["sku"] for p in org2_fleet}

    assert org1_product["sku"] in org1_skus
    assert org2_product["sku"] not in org1_skus
    assert org2_product["sku"] in org2_skus
    assert org1_product["sku"] not in org2_skus


def test_cross_org_webhook_signature_does_not_authenticate(client, db, second_org):
    """
    Epoch 10 PR 12 (webhook redesign, #148): org 2's webhook secret must
    not authenticate a payload against org 1's route — each org's
    signature is only valid against its own org's endpoint, not a
    shared/global one like the old single WEBHOOK_SECRET env var was.
    """
    _set_webhook_secret(db, 1, _ORG1_WEBHOOK_SECRET)
    _set_webhook_secret(db, second_org.id, _ORG2_WEBHOOK_SECRET)
    payload = {
        "source": "generic",
        "events": [
            {"sku": "WGT-001", "event_type": "PURCHASE", "quantity": 1, "external_id": "txn-1"}
        ],
    }

    response = _signed_webhook_request(client, 1, payload, secret=_ORG2_WEBHOOK_SECRET)

    assert response.status_code == 401


def test_webhook_secret_state_is_independent_per_org(client, client_org2, db, second_org):
    """
    Epoch 10 PR 12 (#148): org 1 requiring a signature and org 2 having
    none configured must be two genuinely independent per-org states,
    not one global toggle — proves both directions in the same test.
    """
    _set_webhook_secret(db, 1, _ORG1_WEBHOOK_SECRET)
    # second_org's webhook_secret is left NULL (unset) on purpose.

    org1_product = create_product(client, "Org1 Widget")
    org2_product = create_product(client_org2, "Org2 Widget")

    def _payload(sku):
        return {
            "source": "generic",
            "events": [
                {"sku": sku, "event_type": "PURCHASE", "quantity": 1, "external_id": "txn-1"}
            ],
        }

    unsigned_to_org1 = client.post("/api/webhooks/1/ingest", json=_payload(org1_product["sku"]))
    assert unsigned_to_org1.status_code == 401

    unsigned_to_org2 = client_org2.post(
        f"/api/webhooks/{second_org.id}/ingest", json=_payload(org2_product["sku"])
    )
    assert unsigned_to_org2.status_code == 200
