"""add unit_price to inventory_events

Revision ID: 5e553e59ddf3
Revises: 09cdd17ba9e5
Create Date: 2026-09-04 19:43:20.116893

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e553e59ddf3'
down_revision: Union[str, Sequence[str], None] = '09cdd17ba9e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, additive -- see app/models/inventory_event.py's comment on
    # this column for why. Autogenerate also proposed an index on
    # recipe_items.id -- unrelated pre-existing drift (that column already
    # declares index=True redundantly alongside being the primary key,
    # which Postgres already indexes on its own) -- deliberately excluded
    # here, not part of this change.
    op.add_column(
        "inventory_events", sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("inventory_events", "unit_price")
