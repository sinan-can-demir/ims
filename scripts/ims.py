# scripts/ims.py
#
# Operator CLI wrapping the Makefile/docker compose workflow into one
# command — `ims setup` doubles as the first-run setup wizard (no
# separate wizard needed): brings the stack up, waits for the API to be
# healthy, and walks through creating the first account if none exists
# yet. Scoped to the local/self-hosted dev-quickstart flow (see README's
# "Quickstart (Docker)"), not a substitute for
# docs/deployment/self-hosted.md's production setup (domain, secrets,
# Caddy) — those are inherently deployment-specific decisions no wizard
# should make silently.
#
# Deliberately plain `python scripts/ims.py <command>`, matching every
# other script in this directory (create_user.py, set_user_role.py,
# seed_data.py) — pyproject.toml has no [project]/[build-system] table,
# so a pip-installable `ims` console-script entry point would mean adding
# real packaging infrastructure this repo doesn't have yet, a bigger,
# separate concern than "wrap the Makefile".
#
# Usage:
#   python scripts/ims.py setup
#   python scripts/ims.py start | stop | status
#   python scripts/ims.py backup <destination_dir>
#   python scripts/ims.py restore <archive.tar.gz>

import argparse
import getpass
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Line-buffer stdout even when piped/redirected (not just in a real TTY) —
# without this, this script's own print()s and the subprocess output
# _run() lets inherit stdout can interleave out of order.
sys.stdout.reconfigure(line_buffering=True)

HEALTH_URL = "http://localhost:8000/health"


def _run(cmd: list[str]) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    # shell=False (the default) — every call site passes a fixed argv list
    # (docker/compose subcommands, or a script path + one CLI-supplied
    # path argument), never a shell string, so there's no shell-injection
    # surface here regardless of what that one argument contains.
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode  # noqa: S603


def _wait_for_health(timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:  # noqa: S310 -- fixed localhost URL, not user input
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def cmd_start(_args: argparse.Namespace) -> int:
    print("Starting IMS...")
    return _run(["docker", "compose", "up", "-d"])


def cmd_stop(_args: argparse.Namespace) -> int:
    print("Stopping IMS...")
    return _run(["docker", "compose", "down"])


def cmd_status(_args: argparse.Namespace) -> int:
    print("Container status:")
    _run(["docker", "compose", "ps"])

    print("\nAPI health:")
    if _wait_for_health(timeout=3):
        print(f"✓ healthy ({HEALTH_URL})")
    else:
        print(f"✗ not reachable at {HEALTH_URL}")

    print("\nMigration status:")
    _run(["docker", "compose", "run", "--rm", "migrate", "alembic", "current"])
    return 0


def _create_first_account() -> None:
    from scripts.create_user import create_user

    email = input("Email: ").strip()
    display_name = input("Display name: ").strip()
    role = input("Role [admin/member] (default: admin): ").strip().lower() or "admin"
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("✗ Passwords do not match.")
        raise SystemExit(1)

    try:
        user = create_user(email, password, display_name, role)
    except ValueError as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(f"✓ Created user '{user.email}' (role={user.role.value})")


def cmd_setup(_args: argparse.Namespace) -> int:
    print("=" * 55)
    print("IMS setup")
    print("=" * 55)

    print("\n[1/3] Starting services (docker compose up -d)...")
    if _run(["docker", "compose", "up", "-d"]) != 0:
        print("✗ docker compose up failed — see the output above.")
        return 1

    print("\n[2/3] Waiting for the API to become healthy...")
    if not _wait_for_health(timeout=60):
        print(f"✗ API did not become healthy within 60s ({HEALTH_URL}).")
        print("  Check `docker compose logs api` for details.")
        return 1
    print("✓ API is healthy.")

    print("\n[3/3] Checking for an existing account...")
    from app.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        existing = db.query(User).first()
    finally:
        db.close()

    if existing:
        print(f"✓ Found an existing account ({existing.email}) — skipping account creation.")
    else:
        print("No accounts found yet — let's create your first one.")
        _create_first_account()

    print("\n" + "=" * 55)
    print("✓ Setup complete.")
    print("  API:  http://localhost:8000  (docs at http://localhost:8000/docs)")
    print("  Dashboard: run `make dashboard` (streamlit run dashboard/app.py)")
    print("=" * 55)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    script = PROJECT_ROOT / "scripts" / "backup.sh"
    if not script.exists():
        print(f"✗ {script} not found.")
        return 1
    return _run([str(script), args.destination])


def cmd_restore(args: argparse.Namespace) -> int:
    script = PROJECT_ROOT / "scripts" / "restore.sh"
    if not script.exists():
        print(f"✗ {script} not found.")
        return 1
    return _run([str(script), args.archive])


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ims", description="Operator CLI for running this IMS instance."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "setup", help="First-run setup: start services, create the first account."
    ).set_defaults(func=cmd_setup)
    subparsers.add_parser("start", help="Start all services.").set_defaults(func=cmd_start)
    subparsers.add_parser("stop", help="Stop all services.").set_defaults(func=cmd_stop)
    subparsers.add_parser(
        "status", help="Show container status, API health, and migration state."
    ).set_defaults(func=cmd_status)

    backup_parser = subparsers.add_parser(
        "backup", help="Back up Postgres + local pipeline artifacts."
    )
    backup_parser.add_argument("destination", help="Directory to write the backup archive to.")
    backup_parser.set_defaults(func=cmd_backup)

    restore_parser = subparsers.add_parser(
        "restore", help="Restore from a backup archive (destructive)."
    )
    restore_parser.add_argument("archive", help="Path to an archive created by `ims backup`.")
    restore_parser.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
