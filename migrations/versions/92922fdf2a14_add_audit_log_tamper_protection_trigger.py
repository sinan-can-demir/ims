"""add audit log tamper protection trigger

Revision ID: 92922fdf2a14
Revises: 98a76a12045f
Create Date: 2026-07-26 16:51:20.812301

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92922fdf2a14'
down_revision: Union[str, Sequence[str], None] = '98a76a12045f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A DB-level trigger, not a REVOKE on the app's role — a trigger
    # blocks UPDATE/DELETE regardless of *which* role connects (including
    # a future admin/migration role), so it doesn't quietly stop working
    # if the app ever moves off today's single-shared-role model. A
    # REVOKE would only protect against the one role it's applied to.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation();")
