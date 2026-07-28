"""add organization_id to products suppliers users audit_log

Revision ID: 49570bffe51e
Revises: 6eb479a8a33c
Create Date: 2026-07-28 16:54:03.879922

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49570bffe51e'
down_revision: Union[str, Sequence[str], None] = '6eb479a8a33c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default='1' (the bootstrap org from the prior migration) lets
    # Postgres fill every existing row as part of the ADD COLUMN itself —
    # not a separate UPDATE statement. Two reasons this matters here,
    # beyond just being the established idiom for a constant-value
    # backfill in this repo (role/is_active): (1) it's the efficient path
    # on modern Postgres for a NOT NULL column with a constant default —
    # no full-table rewrite; (2) audit_log has a BEFORE UPDATE trigger
    # (audit_log_append_only, see 92922fdf2a14) that unconditionally
    # rejects row-level UPDATEs — a separate backfill UPDATE statement
    # would be blocked by the app's own tamper-protection trigger.
    #
    # UNLIKE event_id's backfill default, this one is kept permanently,
    # not dropped after backfilling — this is schema-only PR 2 of a
    # 16-PR arc (see ROADMAP.md's EPOCH 10 section); product_service.py,
    # supplier_service.py, and audit_service.py don't get organization_id
    # threaded through until PR 7/10/11, so every write path that creates
    # a Product/Supplier/AuditLog row today still relies on this default
    # to satisfy the NOT NULL constraint until each service is updated.
    # Since ALLOW_MULTIPLE_ORGS stays false for this entire build-out,
    # every real row genuinely does belong to org 1 during that window —
    # this default isn't a workaround masking a bug, it's correct for as
    # long as it's needed. Same permanent-default idiom already
    # established for role/is_active in this codebase.
    op.add_column(
        "products", sa.Column("organization_id", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_index(op.f("ix_products_organization_id"), "products", ["organization_id"])
    op.create_unique_constraint("uq_products_org_id", "products", ["organization_id", "id"])
    op.create_foreign_key(
        "fk_products_organization_id_organizations",
        "products", "organizations", ["organization_id"], ["id"],
    )

    op.add_column(
        "suppliers", sa.Column("organization_id", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_index(op.f("ix_suppliers_organization_id"), "suppliers", ["organization_id"])
    op.create_unique_constraint("uq_suppliers_org_id", "suppliers", ["organization_id", "id"])
    op.create_foreign_key(
        "fk_suppliers_organization_id_organizations",
        "suppliers", "organizations", ["organization_id"], ["id"],
    )

    op.add_column(
        "users", sa.Column("organization_id", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"])
    op.create_unique_constraint("uq_users_org_id", "users", ["organization_id", "id"])
    op.create_foreign_key(
        "fk_users_organization_id_organizations",
        "users", "organizations", ["organization_id"], ["id"],
    )

    # No UniqueConstraint(organization_id, id) here — unlike
    # products/suppliers/users, nothing composite-FKs to audit_log as a
    # parent, it's only ever a child.
    op.add_column(
        "audit_log", sa.Column("organization_id", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_index(op.f("ix_audit_log_organization_id"), "audit_log", ["organization_id"])
    op.create_foreign_key(
        "fk_audit_log_organization_id_organizations",
        "audit_log", "organizations", ["organization_id"], ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_audit_log_organization_id_organizations", "audit_log", type_="foreignkey")
    op.drop_index(op.f("ix_audit_log_organization_id"), table_name="audit_log")
    op.drop_column("audit_log", "organization_id")

    op.drop_constraint("fk_users_organization_id_organizations", "users", type_="foreignkey")
    op.drop_constraint("uq_users_org_id", "users", type_="unique")
    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_column("users", "organization_id")

    op.drop_constraint("fk_suppliers_organization_id_organizations", "suppliers", type_="foreignkey")
    op.drop_constraint("uq_suppliers_org_id", "suppliers", type_="unique")
    op.drop_index(op.f("ix_suppliers_organization_id"), table_name="suppliers")
    op.drop_column("suppliers", "organization_id")

    op.drop_constraint("fk_products_organization_id_organizations", "products", type_="foreignkey")
    op.drop_constraint("uq_products_org_id", "products", type_="unique")
    op.drop_index(op.f("ix_products_organization_id"), table_name="products")
    op.drop_column("products", "organization_id")
