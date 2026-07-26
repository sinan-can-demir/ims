# scripts/set_user_role.py
#
# Promotes/demotes an existing user's role. There's currently no update
# path for any other User field post-creation (see scripts/create_user.py),
# but a role change is a privilege-escalation event on an existing
# principal — worth an audit_log entry even though CLI-driven account
# *creation* itself deliberately isn't audited (SECURITY.md).
#
# actor_id=None on the audit row: this is an operator running a CLI
# script directly against the database, not an authenticated API
# request — there's no session/token to attribute it to, same reasoning
# already used for webhook-sourced events and unknown-email login
# failures (see app/models/audit_log.py).
#
# Usage:
#   python scripts/set_user_role.py --email you@example.com --role admin
#
# Requirements:
#   - Postgres must be reachable at DATABASE_URL (make up)

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audit_service import log_action  # noqa: E402


def set_user_role(email: str, role: str) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise ValueError(f"No user with email '{email}'")

        old_role = user.role
        user.role = role
        db.commit()
        db.refresh(user)

        log_action(
            db,
            actor_id=None,
            action="role_changed",
            detail=f"user_id={user.id} email={email} {old_role.value}->{role}",
        )
        # log_action() commits internally, which expires every object
        # attached to this session (default expire_on_commit) — including
        # `user`. Refresh once more so the caller can read attributes off
        # the returned object after this function's `finally: db.close()`
        # runs, without triggering a lazy-load against a closed session.
        db.refresh(user)
        return user
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Change an existing IMS user's role.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=[role.value for role in UserRole])
    args = parser.parse_args()

    try:
        user = set_user_role(args.email, args.role)
    except ValueError as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(f"✓ Set role of '{user.email}' to '{user.role.value}'")


if __name__ == "__main__":
    main()
