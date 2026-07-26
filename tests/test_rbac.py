# tests/test_rbac.py
#
# Route-level coverage for the admin/member split — 401-for-no-token is
# already covered in tests/test_auth.py (test_replay_without_token_returns_401);
# this file is specifically about 403-for-wrong-role vs 200-for-right-role.

from .utils import create_product


def test_member_gets_403_on_replay(client):
    response = client.post("/api/inventory/replay")
    assert response.status_code == 403


def test_member_gets_403_on_export(client):
    response = client.post("/api/inventory/export")
    assert response.status_code == 403


def test_admin_can_replay(admin_client):
    response = admin_client.post("/api/inventory/replay")
    assert response.status_code == 200


def test_admin_can_export(admin_client, export_paths):
    response = admin_client.post("/api/inventory/export")
    assert response.status_code == 200


def test_member_can_still_create_events(client):
    """The role gate is scoped to replay/export only — every member can
    still record inventory events."""
    product = create_product(client)
    response = client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "PURCHASE",
            "quantity": 5,
            "event_id": "rbac-member-event-1",
        },
    )
    assert response.status_code == 201
