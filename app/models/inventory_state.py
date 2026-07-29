# models/inventory_state.py

from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Integer
from sqlalchemy.orm import relationship

from app.database import Base


class InventoryState(Base):
    """
    Projection table representing the current inventory level
    for each product.

    This table is derived from inventory_events but stores the
    latest snapshot so we don't need to recompute sums every time.
    """

    __tablename__ = "inventory_state"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name="fk_inventory_state_org_product",
        ),
    )

    # One row per product — PK stays product_id (globally unique across
    # orgs), not a composite (organization_id, product_id) PK; see
    # ROADMAP.md's EPOCH 10 section.
    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)

    # Backfilled via products.organization_id (see 688eb809961b).
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    quantity = Column(Integer, nullable=False, server_default="0")

    # Optional relationship. foreign_keys= is required now that there are
    # two FK paths to products (the original single-column product_id FK,
    # plus the new composite org+product_id one from 688eb809961b) — without
    # it SQLAlchemy can't pick a join condition (AmbiguousForeignKeysError).
    product = relationship("Product", foreign_keys=[product_id])
