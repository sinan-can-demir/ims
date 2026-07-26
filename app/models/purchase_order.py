from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import PurchaseOrderStatus


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, index=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)

    status = Column(
        Enum(PurchaseOrderStatus, name="purchase_order_status_enum"),
        nullable=False,
        server_default=PurchaseOrderStatus.DRAFT.value,
    )

    # Always a real human actor — POs are only ever created via an
    # authenticated API call, unlike InventoryEvent.created_by_id (which
    # is nullable for webhook-sourced events with no human actor).
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
