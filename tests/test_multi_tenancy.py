# tests/test_multi_tenancy.py
#
# Cross-org isolation suite for Epoch 10 — starts here (PR 6/16, see
# ROADMAP.md's EPOCH 10 section). Each Epoch 10 PR that org-threads a new
# route/service adds its own isolation tests here rather than scattering
# them across the feature-specific test files.

from .utils import create_product


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
