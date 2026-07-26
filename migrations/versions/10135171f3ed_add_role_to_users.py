"""add role to users

Revision ID: 10135171f3ed
Revises: deb944683c50
Create Date: 2026-07-26 00:14:19.818940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10135171f3ed'
down_revision: Union[str, Sequence[str], None] = 'deb944683c50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


user_role_enum = sa.Enum("admin", "member", name="user_role_enum")


def upgrade() -> None:
    """Upgrade schema."""
    # Postgres native enum type must be created explicitly before an
    # ALTER TABLE ADD COLUMN references it — unlike event_type_enum, which
    # was created implicitly as part of CREATE TABLE in the initial
    # migration, add_column DDL events don't trigger SQLAlchemy's
    # automatic type creation.
    user_role_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column("role", user_role_enum, nullable=False, server_default="member"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "role")
    user_role_enum.drop(op.get_bind(), checkfirst=True)
