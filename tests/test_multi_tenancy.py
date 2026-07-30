# tests/test_multi_tenancy.py
#
# Cross-org isolation suite for Epoch 10 — starts here (PR 6/16, see
# ROADMAP.md's EPOCH 10 section). Each Epoch 10 PR that org-threads a new
# route/service adds its own isolation tests here rather than scattering
# them across the feature-specific test files.

import io
import uuid

import pytest

from app.core.exceptions import ProductSkuNotFoundError
from app.services.product_service import get_product_by_sku

from .utils import create_product


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
