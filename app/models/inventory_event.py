from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import EventType


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    __table_args__ = (
        Index("ix_inventory_events_product_id", "product_id"),
        Index("ix_inventory_events_created_at", "created_at"),
        Index("ix_inventory_events_product_created", "product_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)

    event_id = Column(String, unique=True, nullable=False)

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    event_type = Column(Enum(EventType, name="event_type_enum"), nullable=False)

    quantity = Column(Integer, nullable=False)

    # Permanently nullable by design, not a migration-in-progress state —
    # webhook-sourced events have no human actor, and NULL is honest here;
    # inventing a synthetic "system" user would muddy a real accountability
    # feature.
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
