# tests/test_rbac.py
#
# Route-level coverage for the admin/member split — 401-for-no-token is
# already covered in tests/test_auth.py (test_replay_without_token_returns_401);
# this file is specifically about 403-for-wrong-role vs 200-for-right-role.

import pytest

from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.user import User
from scripts.set_user_role import set_user_role

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


def test_set_user_role_promotes_and_logs_audit_row(set_user_role_db):
    session = set_user_role_db()
    try:
        user = User(
            email="promote-cli@example.com",
            password_hash=hash_password("pw"),
            display_name="Promote Me",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.role == UserRole.MEMBER
    finally:
        session.close()

    updated = set_user_role("promote-cli@example.com", UserRole.ADMIN.value)
    assert updated.role == UserRole.ADMIN

    session = set_user_role_db()
    try:
        entry = (
            session.query(AuditLog)
            .filter(AuditLog.action == "role_changed")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.actor_id is None
        assert "promote-cli@example.com" in entry.detail
        assert "member->admin" in entry.detail
    finally:
        session.close()


def test_set_user_role_rejects_unknown_email(set_user_role_db):
    with pytest.raises(ValueError, match="nobody-cli@example.com"):
        set_user_role("nobody-cli@example.com", UserRole.ADMIN.value)
