"""add waste event type

Revision ID: b1c13d031af9
Revises: 10135171f3ed
Create Date: 2026-07-26 13:24:41.399983

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c13d031af9'
down_revision: Union[str, Sequence[str], None] = '10135171f3ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as
    # long as the new value isn't used in that same transaction — true
    # here, so no special autocommit handling is needed (contrast with
    # user_role_enum in 10135171f3ed, which was a brand-new type created
    # via checkfirst=True, a different situation).
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'WASTE'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE, so removing a value means
    # recreating the type without it. This intentionally has no fallback
    # for existing WASTE rows — the USING cast below will fail loudly if
    # any exist, which is correct: silently coercing real waste events to
    # some other type would be a data loss bug, not a safe downgrade.
    op.execute("ALTER TYPE event_type_enum RENAME TO event_type_enum_old")
    op.execute(
        "CREATE TYPE event_type_enum AS ENUM "
        "('PURCHASE', 'SALE', 'DAMAGE', 'ADJUSTMENT', 'RETURN')"
    )
    op.execute(
        "ALTER TABLE inventory_events "
        "ALTER COLUMN event_type TYPE event_type_enum "
        "USING event_type::text::event_type_enum"
    )
    op.execute("DROP TYPE event_type_enum_old")
