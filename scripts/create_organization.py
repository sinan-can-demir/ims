# scripts/create_organization.py
#
# CLI-only organization creation, same shape as scripts/create_user.py —
# no self-service org-creation endpoint exists (Epoch 10, ROADMAP.md).
# Writes directly via SessionLocal() rather than going through the HTTP API.
#
# A fresh deployment already has a bootstrap org (id=1, "Default
# Organization") from the Epoch 10 migration — this script is for
# provisioning additional orgs on a deployment that actually wants more
# than one tenant. Warns (doesn't block) if ALLOW_MULTIPLE_ORGS is false:
# an operator legitimately provisioning their 2nd tenant needs to be able
# to run this *before* flipping the flag on, not be locked out by it.
#
# Usage:
#   python scripts/create_organization.py --name "Acme Restaurants"
#
# Requirements:
#   - Postgres must be reachable at DATABASE_URL (make up)

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ALLOW_MULTIPLE_ORGS  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.organization import Organization  # noqa: E402


def create_organization(name: str) -> Organization:
    db = SessionLocal()
    try:
        # webhook_secret is NOT NULL (see app/models/organization.py) —
        # every org needs a real one from the moment it exists, since
        # require_webhook_signature() now fails closed on NULL rather
        # than treating it as "verification disabled". This is the only
        # time this value is ever generated fresh; if it's lost, use
        # scripts/rotate_webhook_secret.py to issue a new one.
        org = Organization(name=name, webhook_secret=secrets.token_hex(32))
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new IMS organization.")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    if not ALLOW_MULTIPLE_ORGS:
        print(
            "! ALLOW_MULTIPLE_ORGS is not set to true — this org will exist in the "
            "database, but org-selection UI stays hidden until the flag is turned on."
        )

    org = create_organization(args.name)
    print(f"✓ Created organization '{org.name}' (id={org.id})")
    print(f"  Webhook secret (save this now — it will not be shown again): {org.webhook_secret}")
    print(
        "  Sign X-Webhook-Signature as hex(HMAC-SHA256(secret, raw request body)) "
        f"for POST /api/webhooks/{org.id}/ingest."
    )


if __name__ == "__main__":
    main()
