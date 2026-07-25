"""add created_by_id to inventory_events

Revision ID: c4b86c0d0075
Revises: 3c0ef154426a
Create Date: 2026-07-25 17:45:11.632007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4b86c0d0075'
down_revision: Union[str, Sequence[str], None] = '3c0ef154426a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Permanently nullable by design (webhook-sourced events have no human
    # actor) — no backfill needed, unlike the tighten-a-constraint pattern
    # used elsewhere in this migration history.
    op.add_column('inventory_events', sa.Column('created_by_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_inventory_events_created_by_id'), 'inventory_events', ['created_by_id'], unique=False)
    # Named explicitly (autogenerate emits None here) so downgrade can
    # reference it deterministically instead of relying on whatever name
    # Postgres happens to assign.
    op.create_foreign_key(
        'fk_inventory_events_created_by_id_users',
        'inventory_events', 'users', ['created_by_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_inventory_events_created_by_id_users', 'inventory_events', type_='foreignkey')
    op.drop_index(op.f('ix_inventory_events_created_by_id'), table_name='inventory_events')
    op.drop_column('inventory_events', 'created_by_id')
