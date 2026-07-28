"""add organizations table

Revision ID: 6eb479a8a33c
Revises: 92922fdf2a14
Create Date: 2026-07-28 16:27:38.686117

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6eb479a8a33c'
down_revision: Union[str, Sequence[str], None] = '92922fdf2a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("webhook_secret", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_id"), "organizations", ["id"])

    # Bootstrap row for the Epoch 10 multi-tenancy migration chain — every
    # subsequent PR's backfill (products/suppliers/users/audit_log, then
    # their children) references organization_id=1 as a literal, not a
    # lookup. Explicit id=1 (not sequence-assigned) so every fresh
    # CI/test DB and every existing self-hosted deployment backfills to
    # the same, predictable id. setval() resyncs the sequence past 1 so
    # the next real INSERT (a genuine 2nd org, once ALLOW_MULTIPLE_ORGS
    # is turned on) doesn't collide with it.
    op.execute(
        "INSERT INTO organizations (id, name, is_active) VALUES (1, 'Default Organization', true)"
    )
    op.execute("SELECT setval('organizations_id_seq', 1)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_organizations_id"), table_name="organizations")
    op.drop_table("organizations")
