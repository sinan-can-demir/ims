# tests/test_audit.py

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import InvalidCredentialsError
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import log_action
from app.services.auth_service import authenticate_user

from .utils import create_product


def test_log_action_persists_row(db):
    entry = log_action(db, actor_id=None, action="test_action", organization_id=1, detail="hello")

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


# ---------------------------------------------------------------------------
# DB-level tamper protection (#99) — the trigger only exists on Postgres
# (SQLite has no equivalent), so these require a real Postgres backend.
#
# The `db` fixture provisions schema via Base.metadata.create_all(), which
# only creates ORM-declared tables/columns — it never runs Alembic
# migrations, so the trigger this migration adds isn't present just
# because the table exists. audit_log_trigger below installs the exact
# same SQL the migration runs, so these tests verify the trigger's actual
# logic rather than assuming it's there. The trigger's *migration* itself
# (upgrade/downgrade round-trip) is verified separately, manually, against
# a real `alembic upgrade head` — see the PR description.
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_log_trigger(db):
    db.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log is append-only: % not permitted', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER audit_log_append_only
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_log_mutation();
            """
        )
    )
    db.commit()
    try:
        yield
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log"))
        db.execute(text("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()"))
        db.commit()


@pytest.mark.postgres
def test_audit_log_update_is_rejected_at_db_level(db, audit_log_trigger):
    entry = log_action(
        db, actor_id=None, action="tamper_test_update", organization_id=1, detail="original"
    )
    db.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(
            text("UPDATE audit_log SET detail = 'tampered' WHERE id = :id"), {"id": entry.id}
        )
        db.commit()
    db.rollback()


@pytest.mark.postgres
def test_audit_log_delete_is_rejected_at_db_level(db, audit_log_trigger):
    entry = log_action(
        db, actor_id=None, action="tamper_test_delete", organization_id=1, detail="original"
    )
    db.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry.id})
        db.commit()
    db.rollback()

    # The row must still exist — the DELETE never actually took effect.
    db.expire_all()
    row = db.query(AuditLog).filter(AuditLog.id == entry.id).first()
    assert row is not None
