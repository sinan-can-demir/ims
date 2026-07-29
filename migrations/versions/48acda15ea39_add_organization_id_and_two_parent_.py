"""add organization_id and two-parent composite fks to purchase_order_lines

Revision ID: 48acda15ea39
Revises: 688eb809961b
Create Date: 2026-07-28 22:44:30.112573

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48acda15ea39"
down_revision: Union[str, Sequence[str], None] = "688eb809961b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same join-based-backfill + permanent-server_default shape as PR 4
    # (688eb809961b) — add nullable, UPDATE...FROM the parent, then
    # tighten to NOT NULL *and* set server_default='1' in the same
    # alter_column call. The server_default is not optional here: PR 4's
    # first push omitted it and broke CI's `pipeline` job outright
    # (scripts/seed_data.py-style inserts that don't set organization_id
    # hit a live NOT NULL violation) — purchase_order_service.py's two
    # PurchaseOrderLine(...) call sites (create_purchase_order,
    # add_line_to_purchase_order) don't thread organization_id through
    # until a later Epoch 10 PR either, so every write path here needs
    # the same default until then.
    op.add_column("purchase_order_lines", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE purchase_order_lines
        SET organization_id = purchase_orders.organization_id
        FROM purchase_orders
        WHERE purchase_order_lines.purchase_order_id = purchase_orders.id
        """
    )
    op.alter_column("purchase_order_lines", "organization_id", nullable=False, server_default="1")
    op.create_index(
        op.f("ix_purchase_order_lines_organization_id"),
        "purchase_order_lines",
        ["organization_id"],
    )
    op.create_foreign_key(
        "fk_purchase_order_lines_organization_id_organizations",
        "purchase_order_lines",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    # The one table in this arc with composite FKs to TWO independent
    # org-scoped parents that must agree with each other, not just with
    # this row. purchase_order_id and product_id are both NOT NULL, so
    # (unlike inventory_events.created_by_id in PR 4) there's no
    # MATCH SIMPLE/FULL nuance to consider here — every row's
    # organization_id is validated against both parents unconditionally.
    # On today's single-tenant data this cross-check is trivially
    # satisfied (every parent is org 1), but going forward the DB now
    # structurally enforces that a line's product and its purchase
    # order always belong to the same org — a line can't be inserted
    # (or updated) pointing at a product from one org while its
    # purchase_order_id points at a PO from another, even though
    # nothing in the service layer checks this yet.
    op.create_foreign_key(
        "fk_purchase_order_lines_org_purchase_order",
        "purchase_order_lines",
        "purchase_orders",
        ["organization_id", "purchase_order_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_purchase_order_lines_org_product",
        "purchase_order_lines",
        "products",
        ["organization_id", "product_id"],
        ["organization_id", "id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_purchase_order_lines_org_product", "purchase_order_lines", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_purchase_order_lines_org_purchase_order",
        "purchase_order_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_purchase_order_lines_organization_id_organizations",
        "purchase_order_lines",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_purchase_order_lines_organization_id"), table_name="purchase_order_lines"
    )
    op.drop_column("purchase_order_lines", "organization_id")
