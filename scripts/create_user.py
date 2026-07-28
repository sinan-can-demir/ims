# scripts/create_user.py
#
# CLI-only user creation for v1 — there's no self-service registration
# endpoint (see the user-accounts design doc), so this is the only way to
# get a User row to log in with. Mirrors scripts/seed_data.py's pattern of
# writing directly via SessionLocal() rather than going through the HTTP API.
#
# Usage:
#   python scripts/create_user.py --email you@example.com --display-name "Your Name"
#   python scripts/create_user.py --email admin@example.com --display-name Admin --role admin
#
# Password is prompted interactively (not passed as an argument) so it
# never ends up in shell history or process listings.
#
# --role defaults to "member" — there's no "first user is admin" magic
# (a footgun: race conditions on concurrent first-run, silent behavior
# nobody reviewed). To promote/demote an existing account, use
# scripts/set_user_role.py instead of re-running this.
#
# --organization-id defaults to 1 (the bootstrap org every deployment has,
# see Epoch 10's organizations migration) — matches the single-tenant
# shape every self-hosted deployment actually is unless ALLOW_MULTIPLE_ORGS
# is on and scripts/create_organization.py has been used to provision a
# real 2nd org.
#
# Requirements:
#   - Postgres must be reachable at DATABASE_URL (make up)

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402


def create_user(
    email: str,
    password: str,
    display_name: str,
    role: str = UserRole.MEMBER.value,
    organization_id: int = 1,
) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            role=role,
            organization_id=organization_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise ValueError(f"A user with email '{email}' already exists")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new IMS user account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.MEMBER.value,
    )
    parser.add_argument("--organization-id", type=int, default=1)
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("✗ Passwords do not match.")
        raise SystemExit(1)

    try:
        user = create_user(args.email, password, args.display_name, args.role, args.organization_id)
    except ValueError as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(
        f"✓ Created user '{user.email}' "
        f"(id={user.id}, role={user.role.value}, organization_id={user.organization_id})"
    )


if __name__ == "__main__":
    main()
