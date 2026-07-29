from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class RecipeItem(Base):
    """
    One ingredient line of a dish's recipe/BOM: selling `finished_product_id`
    consumes `quantity` units of `component_product_id`. Deliberately one
    level deep — component products are assumed to be raw ingredients, not
    themselves finished products with their own recipe, so there's no
    recursive cascade or cycle to guard against.
    """

    __tablename__ = "recipe_items"

    __table_args__ = (
        UniqueConstraint("finished_product_id", "component_product_id", name="uq_recipe_item_pair"),
        CheckConstraint("quantity > 0", name="ck_recipe_item_quantity_positive"),
        CheckConstraint(
            "finished_product_id != component_product_id", name="ck_recipe_item_no_self_reference"
        ),
        # Two independent composite FKs — each alone already forces its
        # column to share the recipe_item row's org, so together they
        # guarantee a recipe can never link two products from different
        # orgs. No extra CHECK needed on top of these. See 688eb809961b.
        ForeignKeyConstraint(
            ["organization_id", "finished_product_id"],
            ["products.organization_id", "products.id"],
            name="fk_recipe_items_org_finished_product",
        ),
        ForeignKeyConstraint(
            ["organization_id", "component_product_id"],
            ["products.organization_id", "products.id"],
            name="fk_recipe_items_org_component_product",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Backfilled via finished_product_id's products.organization_id (see
    # 688eb809961b).
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    finished_product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    component_product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    quantity = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
