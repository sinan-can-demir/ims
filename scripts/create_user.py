# scripts/create_user.py
#
# CLI-only user creation for v1 — there's no self-service registration
# endpoint (see the user-accounts design doc), so this is the only way to
# get a User row to log in with. Mirrors scripts/seed_data.py's pattern of
# writing directly via SessionLocal() rather than going through the HTTP API.
#
# Usage:
#   python scripts/create_user.py --email you@example.com --display-name "Your Name"
#
# Password is prompted interactively (not passed as an argument) so it
# never ends up in shell history or process listings.
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
from app.models.user import User  # noqa: E402


def create_user(email: str, password: str, display_name: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
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
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("✗ Passwords do not match.")
        raise SystemExit(1)

    try:
        user = create_user(args.email, password, args.display_name)
    except ValueError as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(f"✓ Created user '{user.email}' (id={user.id})")


if __name__ == "__main__":
    main()
