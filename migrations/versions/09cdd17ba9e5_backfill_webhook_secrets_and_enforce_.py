"""backfill webhook secrets and enforce not null

Revision ID: 09cdd17ba9e5
Revises: 1fe4a0d84796
Create Date: 2026-09-03 15:08:29.601268

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09cdd17ba9e5'
down_revision: Union[str, Sequence[str], None] = '1fe4a0d84796'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    require_webhook_signature() (app/core/auth.py) now fails closed on
    NULL webhook_secret instead of treating it as "signature
    verification disabled" — the only real provisioning path
    (scripts/create_organization.py, before this change) never set the
    value, so every org in every existing deployment has webhook_secret
    IS NULL right now. This is a hard break for any live integration:
    each org's secret printed below is the only chance to see it via
    this migration; reconfigure real senders with it, or issue a fresh
    one afterward with scripts/rotate_webhook_secret.py.
    """
    conn = op.get_bind()
    org_ids = [row[0] for row in conn.execute(
        sa.text("SELECT id FROM organizations WHERE webhook_secret IS NULL")
    )]

    for org_id in org_ids:
        secret = secrets.token_hex(32)
        conn.execute(
            sa.text("UPDATE organizations SET webhook_secret = :secret WHERE id = :id"),
            {"secret": secret, "id": org_id},
        )
        print(f"organization_id={org_id}: new webhook_secret={secret}")

    op.alter_column("organizations", "webhook_secret", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("organizations", "webhook_secret", existing_type=sa.String(), nullable=True)
