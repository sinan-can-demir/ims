from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
)
from sqlalchemy.sql import func

from app.database import Base


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),
        # Two independent composite FKs to two different org-scoped
        # parents — both purchase_order_id and product_id are NOT NULL,
        # so (unlike inventory_events.created_by_id, Epoch 10 PR 4) there's
        # no MATCH SIMPLE/FULL nuance here. See migrations/versions/
        # 48acda15ea39 for the full "why isolated" reasoning.
        ForeignKeyConstraint(
            ["organization_id", "purchase_order_id"],
            ["purchase_orders.organization_id", "purchase_orders.id"],
            name="fk_purchase_order_lines_org_purchase_order",
        ),
        ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name="fk_purchase_order_lines_org_product",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Backfilled via purchase_orders.organization_id (see 48acda15ea39).
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    purchase_order_id = Column(
        Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True
    )

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    quantity = Column(Integer, nullable=False)

    unit_cost = Column(Numeric(10, 2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
