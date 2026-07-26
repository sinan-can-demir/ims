from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.sql import func

from app.database import Base


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    __table_args__ = (CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),)

    id = Column(Integer, primary_key=True, index=True)

    purchase_order_id = Column(
        Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True
    )

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    quantity = Column(Integer, nullable=False)

    unit_cost = Column(Numeric(10, 2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
