"""add recipe items table and product unit column

Revision ID: 8cbd312babfe
Revises: b1c13d031af9
Create Date: 2026-07-26 13:40:25.005582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cbd312babfe'
down_revision: Union[str, Sequence[str], None] = 'b1c13d031af9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("products", sa.Column("unit", sa.String(), nullable=True))

    op.create_table(
        "recipe_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("finished_product_id", sa.Integer(), nullable=False),
        sa.Column("component_product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["finished_product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["component_product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finished_product_id", "component_product_id", name="uq_recipe_item_pair"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_recipe_item_quantity_positive"),
        sa.CheckConstraint(
            "finished_product_id != component_product_id", name="ck_recipe_item_no_self_reference"
        ),
    )
    op.create_index(
        op.f("ix_recipe_items_finished_product_id"), "recipe_items", ["finished_product_id"]
    )
    op.create_index(
        op.f("ix_recipe_items_component_product_id"), "recipe_items", ["component_product_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_recipe_items_component_product_id"), table_name="recipe_items")
    op.drop_index(op.f("ix_recipe_items_finished_product_id"), table_name="recipe_items")
    op.drop_table("recipe_items")
    op.drop_column("products", "unit")
