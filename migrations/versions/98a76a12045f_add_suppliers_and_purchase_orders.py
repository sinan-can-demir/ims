"""add suppliers and purchase orders

Revision ID: 98a76a12045f
Revises: 8cbd312babfe
Create Date: 2026-07-26 14:19:42.173325

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98a76a12045f'
down_revision: Union[str, Sequence[str], None] = '8cbd312babfe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_suppliers_id"), "suppliers", ["id"])

    # No explicit .create() call needed here — unlike add_role_to_users'
    # user_role_enum (added via add_column, which doesn't auto-create
    # types), create_table DOES trigger automatic enum creation, same as
    # event_type_enum in the initial schema migration. An explicit create
    # first actually collides with that auto-create (DuplicateObject).
    purchase_order_status_enum = sa.Enum(
        "DRAFT", "SUBMITTED", "RECEIVED", name="purchase_order_status_enum"
    )

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("status", purchase_order_status_enum, nullable=False, server_default="DRAFT"),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_purchase_orders_id"), "purchase_orders", ["id"])
    op.create_index(op.f("ix_purchase_orders_supplier_id"), "purchase_orders", ["supplier_id"])
    op.create_index(
        op.f("ix_purchase_orders_created_by_id"), "purchase_orders", ["created_by_id"]
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),
    )
    op.create_index(op.f("ix_purchase_order_lines_id"), "purchase_order_lines", ["id"])
    op.create_index(
        op.f("ix_purchase_order_lines_purchase_order_id"),
        "purchase_order_lines",
        ["purchase_order_id"],
    )
    op.create_index(
        op.f("ix_purchase_order_lines_product_id"), "purchase_order_lines", ["product_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_purchase_order_lines_product_id"), table_name="purchase_order_lines")
    op.drop_index(
        op.f("ix_purchase_order_lines_purchase_order_id"), table_name="purchase_order_lines"
    )
    op.drop_index(op.f("ix_purchase_order_lines_id"), table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")

    op.drop_index(op.f("ix_purchase_orders_created_by_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_supplier_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_id"), table_name="purchase_orders")
    op.drop_table("purchase_orders")

    sa.Enum(name="purchase_order_status_enum").drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_suppliers_id"), table_name="suppliers")
    op.drop_table("suppliers")
