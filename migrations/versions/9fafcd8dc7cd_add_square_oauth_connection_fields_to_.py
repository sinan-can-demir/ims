"""add square oauth connection fields to organizations

Revision ID: 9fafcd8dc7cd
Revises: 5e553e59ddf3
Create Date: 2026-09-04 20:05:34.997219

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9fafcd8dc7cd'
down_revision: Union[str, Sequence[str], None] = '5e553e59ddf3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate also proposed an index on recipe_items.id -- unrelated
    # pre-existing drift (same as migrations/versions/5e553e59ddf3),
    # deliberately excluded, not part of this change.
    op.add_column("organizations", sa.Column("square_access_token", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("square_refresh_token", sa.String(), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("square_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("organizations", sa.Column("square_merchant_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("organizations", "square_merchant_id")
    op.drop_column("organizations", "square_token_expires_at")
    op.drop_column("organizations", "square_refresh_token")
    op.drop_column("organizations", "square_access_token")
