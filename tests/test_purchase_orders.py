# tests/test_purchase_orders.py

import uuid
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import ProductNotFoundError
from app.core.security import hash_password
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.supplier import Supplier
from app.models.user import User
from app.services import purchase_order_service

from .utils import create_product
from .utils import create_supplier as _create_supplier


def _quantity(client, product_id):
    return client.get(f"/api/inventory/{product_id}").json()["quantity"]


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


def test_create_supplier(client):
    response = client.post(
        "/api/suppliers", json={"name": "Acme Foods", "contact_email": "orders@acme.example"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Foods"
    assert body["contact_email"] == "orders@acme.example"


def test_list_suppliers(client):
    _create_supplier(client, "Acme Foods")
    _create_supplier(client, "Beta Produce")

    response = client.get("/api/suppliers")
    assert response.status_code == 200
    names = {s["name"] for s in response.json()}
    assert {"Acme Foods", "Beta Produce"} <= names


# ---------------------------------------------------------------------------
# PO lifecycle: create (draft) -> submit -> receive
# ---------------------------------------------------------------------------


def test_create_purchase_order_with_lines(client):
    supplier = _create_supplier(client)
    ingredient = create_product(client, "Flour")

    response = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "lines": [{"product_id": ingredient["id"], "quantity": 50, "unit_cost": 1.25}],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DRAFT"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["quantity"] == 50


def test_create_purchase_order_unknown_supplier_404(client):
    response = client.post("/api/purchase-orders", json={"supplier_id": 999999, "lines": []})
    assert response.status_code == 404


def test_create_purchase_order_unknown_product_404(client):
    supplier = _create_supplier(client)
    response = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "lines": [{"product_id": 999999, "quantity": 1}]},
    )
    assert response.status_code == 404


def test_add_line_to_draft_po(client):
    supplier = _create_supplier(client)
    ingredient = create_product(client, "Flour")
    po = client.post(
        "/api/purchase-orders", json={"supplier_id": supplier["id"], "lines": []}
    ).json()

    response = client.post(
        f"/api/purchase-orders/{po['id']}/lines",
        json={"product_id": ingredient["id"], "quantity": 20},
    )
    assert response.status_code == 201
    assert response.json()["quantity"] == 20


def test_submit_requires_at_least_one_line(client):
    supplier = _create_supplier(client)
    po = client.post(
        "/api/purchase-orders", json={"supplier_id": supplier["id"], "lines": []}
    ).json()

    response = client.post(f"/api/purchase-orders/{po['id']}/submit")
    assert response.status_code == 400


def test_full_lifecycle_submit_then_receive_updates_inventory(client, db):
    supplier = _create_supplier(client)
    flour = create_product(client, "Flour")
    sugar = create_product(client, "Sugar")

    po = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "lines": [
                {"product_id": flour["id"], "quantity": 50},
                {"product_id": sugar["id"], "quantity": 20},
            ],
        },
    ).json()

    submitted = client.post(f"/api/purchase-orders/{po['id']}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"

    received = client.post(f"/api/purchase-orders/{po['id']}/receive")
    assert received.status_code == 200
    assert received.json()["status"] == "RECEIVED"

    assert _quantity(client, flour["id"]) == 50
    assert _quantity(client, sugar["id"]) == 20

    from app.models.audit_log import AuditLog

    actions = {a.action for a in db.query(AuditLog).all()}
    assert "po_submitted" in actions
    assert "po_received" in actions
    # Both rows must be attributed to the org that actually submitted/
    # received the PO, not silently misattributed to some other org.
    for action in ("po_submitted", "po_received"):
        entry = db.query(AuditLog).filter(AuditLog.action == action).first()
        assert entry.organization_id == 1


def test_cannot_edit_line_after_submit(client):
    supplier = _create_supplier(client)
    flour = create_product(client, "Flour")
    po = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "lines": [{"product_id": flour["id"], "quantity": 10}],
        },
    ).json()
    line_id = po["lines"][0]["id"]

    client.post(f"/api/purchase-orders/{po['id']}/submit")

    response = client.patch(f"/api/purchase-orders/lines/{line_id}", json={"quantity": 99})
    assert response.status_code == 400


def test_cannot_receive_a_draft_po(client):
    supplier = _create_supplier(client)
    flour = create_product(client, "Flour")
    po = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "lines": [{"product_id": flour["id"], "quantity": 10}],
        },
    ).json()

    response = client.post(f"/api/purchase-orders/{po['id']}/receive")
    assert response.status_code == 400


def test_list_purchase_orders_filters_by_status(client):
    supplier = _create_supplier(client)
    flour = create_product(client, "Flour")

    draft_po = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "lines": [{"product_id": flour["id"], "quantity": 5}]},
    ).json()

    submitted_po = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "lines": [{"product_id": flour["id"], "quantity": 5}]},
    ).json()
    client.post(f"/api/purchase-orders/{submitted_po['id']}/submit")

    drafts = client.get("/api/purchase-orders", params={"status": "DRAFT"}).json()
    submitted = client.get("/api/purchase-orders", params={"status": "SUBMITTED"}).json()

    assert draft_po["id"] in [p["id"] for p in drafts]
    assert submitted_po["id"] in [p["id"] for p in submitted]
    assert draft_po["id"] not in [p["id"] for p in submitted]


# ---------------------------------------------------------------------------
# Generate a draft PO from a forecast/restock recommendation
# ---------------------------------------------------------------------------


def test_generate_from_forecast_creates_draft(client):
    supplier = _create_supplier(client)
    ingredient = create_product(client, "Flour")

    mock_forecast_df = pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [15.0] * 7,
            "yhat_lower": [10.0] * 7,
            "yhat_upper": [20.0] * 7,
        }
    )

    with patch("app.services.restock_service.forecast", return_value=mock_forecast_df):
        response = client.post(
            f"/api/purchase-orders/generate/{ingredient['id']}",
            params={"supplier_id": supplier["id"]},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DRAFT"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["product_id"] == ingredient["id"]
    assert body["lines"][0]["quantity"] > 0


def test_generate_from_forecast_no_restock_needed(client):
    supplier = _create_supplier(client)
    ingredient = create_product(client, "Flour")

    # Plenty of stock, tiny projected demand -> recommended_order_qty == 0
    client.post(
        "/api/inventory/events",
        json={
            "product_id": ingredient["id"],
            "event_type": "PURCHASE",
            "quantity": 10000,
            "event_id": "evt-plenty",
        },
    )

    mock_forecast_df = pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [1.0] * 7,
            "yhat_lower": [0.0] * 7,
            "yhat_upper": [2.0] * 7,
        }
    )

    with patch("app.services.restock_service.forecast", return_value=mock_forecast_df):
        response = client.post(
            f"/api/purchase-orders/generate/{ingredient['id']}",
            params={"supplier_id": supplier["id"]},
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Receive is retry-safe (idempotent per line) even if it fails partway
# ---------------------------------------------------------------------------


def test_receive_is_retry_safe_after_partial_failure(client, db):
    supplier = _create_supplier(client)
    flour = create_product(client, "Flour")
    sugar = create_product(client, "Sugar")

    po = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "lines": [
                {"product_id": flour["id"], "quantity": 50},
                {"product_id": sugar["id"], "quantity": 20},
            ],
        },
    ).json()
    client.post(f"/api/purchase-orders/{po['id']}/submit")

    real_record_event = purchase_order_service.record_event
    call_count = {"n": 0}

    def _fail_on_second_line(
        db_, product_id, event_type, quantity, event_id, actor_id, organization_id
    ):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise ProductNotFoundError(product_id)
        return real_record_event(
            db_, product_id, event_type, quantity, event_id, actor_id, organization_id
        )

    with patch.object(purchase_order_service, "record_event", side_effect=_fail_on_second_line):
        response = client.post(f"/api/purchase-orders/{po['id']}/receive")
    assert response.status_code == 404

    # First line's event was already committed by record_event itself,
    # even though the overall receive failed and never marked RECEIVED.
    assert _quantity(client, flour["id"]) == 50

    from app.models.purchase_order import PurchaseOrder

    refreshed = db.query(PurchaseOrder).filter(PurchaseOrder.id == po["id"]).first()
    assert refreshed.status.value == "SUBMITTED"

    # Retry with the real record_event — line 1 no-ops (already applied,
    # same deterministic event_id), line 2 now succeeds.
    retry = client.post(f"/api/purchase-orders/{po['id']}/receive")
    assert retry.status_code == 200
    assert retry.json()["status"] == "RECEIVED"

    assert _quantity(client, flour["id"]) == 50  # not double-counted
    assert _quantity(client, sugar["id"]) == 20


@pytest.mark.postgres
def test_purchase_order_composite_fk_rejects_cross_org_supplier(db, second_org):
    """
    DB-enforced, not just application-checked: a hand-inserted
    purchase_orders row can't point at a supplier belonging to a
    different org. See migrations/versions/688eb809961b.
    """
    org1_user = User(
        email=f"po-fk-test-{uuid.uuid4()}@example.com",
        password_hash=hash_password("po-fk-test-password"),
        display_name="PO FK Test",
        organization_id=1,
    )
    org2_supplier = Supplier(organization_id=second_org.id, name="Org2 Supplier")
    db.add_all([org1_user, org2_supplier])
    db.commit()
    db.refresh(org1_user)
    db.refresh(org2_supplier)

    db.add(
        PurchaseOrder(
            organization_id=1,
            supplier_id=org2_supplier.id,
            created_by_id=org1_user.id,
        )
    )
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()


@pytest.mark.postgres
def test_purchase_order_line_composite_fk_rejects_product_from_different_org_than_po(
    db, second_org
):
    """
    The two-parent cross-check (Epoch 10 PR 5, see migrations/versions/
    48acda15ea39): a purchase_order_line's product and its purchase_order
    must agree on org. Constructed directly at the DB layer, not through
    purchase_order_service, to prove it's DB-enforced.
    """
    org1_supplier = Supplier(organization_id=1, name="Org1 Supplier")
    org1_user = User(
        email=f"po-line-fk-test-{uuid.uuid4()}@example.com",
        password_hash=hash_password("po-line-fk-test-password"),
        display_name="PO Line FK Test",
        organization_id=1,
    )
    org2_product = Product(
        organization_id=second_org.id, name="Org2 Widget", sku=f"sku-{uuid.uuid4()}"
    )
    db.add_all([org1_supplier, org1_user, org2_product])
    db.commit()
    db.refresh(org1_supplier)
    db.refresh(org1_user)
    db.refresh(org2_product)

    org1_po = PurchaseOrder(
        organization_id=1, supplier_id=org1_supplier.id, created_by_id=org1_user.id
    )
    db.add(org1_po)
    db.commit()
    db.refresh(org1_po)

    db.add(
        PurchaseOrderLine(
            organization_id=1,
            purchase_order_id=org1_po.id,
            product_id=org2_product.id,
            quantity=1,
        )
    )
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()
