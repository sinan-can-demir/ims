import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from app.models.enums import EventType
from app.models.inventory_event import InventoryEvent
from app.models.inventory_state import InventoryState
from app.models.product import Product
from app.models.user import User

from .utils import create_product


def test_inventory_flow(client):
    # 1. Create product
    product = create_product(client)
    product_id = product["id"]

    # 2. Purchase +50
    client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": "PURCHASE",
            "quantity": 50,
            "event_id": "evt-1",
        },
    )

    # 3. Sale -10
    client.post(
        "/api/inventory/events",
        json={"product_id": product_id, "event_type": "SALE", "quantity": 10, "event_id": "evt-2"},
    )

    # 4. Get inventory
    response = client.get(f"/api/inventory/{product_id}")

    assert response.status_code == 200
    assert response.json()["quantity"] == 40


@pytest.mark.postgres
def test_oversell_protection(client):

    product = create_product(client)
    product_id = product["id"]

    # No stock yet → should fail
    response = client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": "SALE",
            "quantity": 10,
            "event_id": "evt-oversell",
        },
    )

    assert response.status_code == 400


def test_direct_create_event_records_created_by_id(client, db):
    product = create_product(client)
    current_user = db.query(User).filter(User.email == "test-client@example.com").first()

    response = client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "PURCHASE",
            "quantity": 10,
            "event_id": "evt-attribution",
        },
    )

    assert response.status_code == 201
    assert response.json()["created_by_id"] == current_user.id


def test_projection_consistency(client):
    product = create_product(client)
    pid = product["id"]

    client.post(
        "/api/inventory/events",
        json={"product_id": pid, "event_type": "PURCHASE", "quantity": 20, "event_id": "evt-a"},
    )

    client.post(
        "/api/inventory/events",
        json={"product_id": pid, "event_type": "SALE", "quantity": 5, "event_id": "evt-b"},
    )

    response = client.get(f"/api/inventory/{pid}")

    assert response.json()["quantity"] == 15


@pytest.mark.postgres
def test_inventory_event_composite_fk_rejects_cross_org_product(db, second_org):
    """
    DB-enforced, not just application-checked: a hand-inserted
    inventory_events row can't point at a product belonging to a
    different org, even though nothing in the service layer threads
    organization_id yet (Epoch 10 PR 4/16, see migrations/versions/
    688eb809961b).
    """
    org2_product = Product(
        organization_id=second_org.id, name="Org2 Widget", sku=f"sku-{uuid.uuid4()}"
    )
    db.add(org2_product)
    db.commit()
    db.refresh(org2_product)

    db.add(
        InventoryEvent(
            event_id=f"evt-{uuid.uuid4()}",
            organization_id=1,
            product_id=org2_product.id,
            event_type=EventType.PURCHASE,
            quantity=1,
        )
    )
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()


@pytest.mark.postgres
def test_inventory_state_composite_fk_rejects_cross_org_product(db, second_org):
    org2_product = Product(
        organization_id=second_org.id, name="Org2 Widget", sku=f"sku-{uuid.uuid4()}"
    )
    db.add(org2_product)
    db.commit()
    db.refresh(org2_product)

    db.add(InventoryState(product_id=org2_product.id, organization_id=1, quantity=0))
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()
