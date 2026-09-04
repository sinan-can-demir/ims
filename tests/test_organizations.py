# tests/test_organizations.py
#
# Coverage for scripts/create_organization.py and
# scripts/rotate_webhook_secret.py, both introduced/changed as part of
# closing the webhook auth bypass (require_webhook_signature now fails
# closed on NULL webhook_secret, so every org needs a real one from the
# moment it exists).

import pytest

from app.models.audit_log import AuditLog
from scripts.create_organization import create_organization
from scripts.rotate_webhook_secret import rotate_webhook_secret


def test_create_organization_generates_random_webhook_secret(create_organization_db):
    org_a = create_organization("Org A")
    org_b = create_organization("Org B")

    assert org_a.webhook_secret is not None
    assert org_b.webhook_secret is not None
    assert org_a.webhook_secret != org_b.webhook_secret
    # secrets.token_hex(32) -> 64 hex chars
    assert len(org_a.webhook_secret) == 64


def test_rotate_webhook_secret_issues_new_value_and_logs_audit_row(
    create_organization_db, rotate_webhook_secret_db
):
    org = create_organization("Rotate Me")
    old_secret = org.webhook_secret

    rotated = rotate_webhook_secret(org.id)

    assert rotated.webhook_secret != old_secret
    assert len(rotated.webhook_secret) == 64

    session = rotate_webhook_secret_db()
    try:
        entry = (
            session.query(AuditLog)
            .filter(AuditLog.action == "webhook_secret_rotated")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.actor_id is None
        assert entry.organization_id == org.id
        assert f"organization_id={org.id}" in entry.detail
    finally:
        session.close()


def test_rotate_webhook_secret_rejects_unknown_org(rotate_webhook_secret_db):
    with pytest.raises(ValueError, match="999999"):
        rotate_webhook_secret(999999)
