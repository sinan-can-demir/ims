# tests/test_audit.py

import pytest

from app.core.exceptions import InvalidCredentialsError
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import log_action
from app.services.auth_service import authenticate_user

from .utils import create_product


def test_log_action_persists_row(db):
    entry = log_action(db, actor_id=None, action="test_action", detail="hello")

    assert entry.id is not None
    row = db.query(AuditLog).filter(AuditLog.id == entry.id).first()
    assert row.action == "test_action"
    assert row.detail == "hello"
    assert row.actor_id is None


def test_replay_endpoint_logs_audit_row(admin_client, db):
    # POST /api/inventory/replay is admin-gated — use admin_client.
    current_user = db.query(User).filter(User.email == "test-admin@example.com").first()
    product = create_product(admin_client)
    admin_client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "PURCHASE",
            "quantity": 10,
            "event_id": "audit-replay-1",
        },
    )

    response = admin_client.post("/api/inventory/replay")
    assert response.status_code == 200

    entry = (
        db.query(AuditLog).filter(AuditLog.action == "replay").order_by(AuditLog.id.desc()).first()
    )
    assert entry is not None
    assert entry.actor_id == current_user.id
    assert "events_processed=1" in entry.detail


def test_export_endpoint_logs_audit_row(admin_client, db, export_paths):
    # POST /api/inventory/export is admin-gated — use admin_client.
    current_user = db.query(User).filter(User.email == "test-admin@example.com").first()
    product = create_product(admin_client)
    admin_client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "PURCHASE",
            "quantity": 10,
            "event_id": "audit-export-1",
        },
    )
    db.expire_all()

    response = admin_client.post("/api/inventory/export")
    assert response.status_code == 200

    entry = (
        db.query(AuditLog).filter(AuditLog.action == "export").order_by(AuditLog.id.desc()).first()
    )
    assert entry is not None
    assert entry.actor_id == current_user.id


def test_login_failed_unknown_email_logs_null_actor(db):
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "nobody-audit@example.com", "whatever")

    entry = (
        db.query(AuditLog)
        .filter(AuditLog.action == "login_failed")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.actor_id is None
    assert entry.detail == "nobody-audit@example.com"


def test_login_failed_wrong_password_logs_actor_id(db):
    user = User(
        email="audit-wrongpw@example.com",
        password_hash=hash_password("correct-password"),
        display_name="Audit User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "audit-wrongpw@example.com", "wrong-password")

    entry = (
        db.query(AuditLog)
        .filter(AuditLog.action == "login_failed")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.actor_id == user.id


def test_login_failed_deactivated_user_logs_actor_id(db):
    user = User(
        email="audit-deactivated@example.com",
        password_hash=hash_password("correct-password"),
        display_name="Audit User",
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "audit-deactivated@example.com", "correct-password")

    entry = (
        db.query(AuditLog)
        .filter(AuditLog.action == "login_failed")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.actor_id == user.id
