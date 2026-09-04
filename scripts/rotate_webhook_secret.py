# scripts/rotate_webhook_secret.py
#
# Issues a fresh webhook_secret for an existing organization — the only
# recovery path if an operator loses the value printed once at creation
# time (scripts/create_organization.py) or by the backfill migration
# that introduced webhook_secret NOT NULL. Rotating deliberately
# invalidates the old secret immediately: any integration still signing
# with it starts getting 401s until reconfigured with the new value.
#
# Usage:
#   python scripts/rotate_webhook_secret.py --org-id 1
#
# Requirements:
#   - Postgres must be reachable at DATABASE_URL (make up)

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.services.audit_service import log_action  # noqa: E402


def rotate_webhook_secret(organization_id: int) -> Organization:
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if org is None:
            raise ValueError(f"No organization with id {organization_id}")

        org.webhook_secret = secrets.token_hex(32)
        db.commit()
        db.refresh(org)

        # actor_id=None — CLI-driven, no authenticated session to
        # attribute this to, same reasoning as set_user_role.py's
        # role_changed entries.
        log_action(
            db,
            actor_id=None,
            action="webhook_secret_rotated",
            detail=f"organization_id={org.id}",
            organization_id=org.id,
        )
        # log_action() commits internally, which expires every object
        # attached to this session (default expire_on_commit) —
        # including `org`. Refresh once more so the caller can read
        # attributes off the returned object after this function's
        # `finally: db.close()` runs. Same pattern as set_user_role.py.
        db.refresh(org)
        return org
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate an existing IMS organization's webhook signing secret."
    )
    parser.add_argument("--org-id", type=int, required=True)
    args = parser.parse_args()

    try:
        org = rotate_webhook_secret(args.org_id)
    except ValueError as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(f"✓ Rotated webhook secret for organization '{org.name}' (id={org.id})")
    print(
        f"  New webhook secret (save this now — it will not be shown again): {org.webhook_secret}"
    )
    print(
        "  Any integration still signing with the old secret will start "
        "receiving 401s until reconfigured."
    )


if __name__ == "__main__":
    main()
