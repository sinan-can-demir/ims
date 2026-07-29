from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import EventType


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    __table_args__ = (
        Index("ix_inventory_events_product_id", "product_id"),
        Index("ix_inventory_events_created_at", "created_at"),
        Index("ix_inventory_events_product_created", "product_id", "created_at"),
        ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name="fk_inventory_events_org_product",
        ),
        # MATCH SIMPLE (SQLAlchemy's default when `match` is unset) —
        # required, not incidental, since created_by_id is nullable. See
        # migrations/versions/688eb809961b for the full reasoning.
        ForeignKeyConstraint(
            ["organization_id", "created_by_id"],
            ["users.organization_id", "users.id"],
            name="fk_inventory_events_org_created_by",
        ),
        # Epoch 10 PR 6 (see migrations/versions/ffdda217be31): event_id
        # moved from globally-unique to UNIQUE(organization_id, event_id)
        # — two orgs can now record the same event_id string independently.
        UniqueConstraint("organization_id", "event_id", name="uq_inventory_events_org_event_id"),
    )

    id = Column(Integer, primary_key=True)

    # No unique=True here — uniqueness is now org-scoped, see
    # uq_inventory_events_org_event_id above.
    event_id = Column(String, nullable=False)

    # Backfilled via products.organization_id (see 688eb809961b) — kept
    # permanently, not dropped, until inventory_service.py threads
    # organization_id through explicitly in a later Epoch 10 PR.
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    event_type = Column(Enum(EventType, name="event_type_enum"), nullable=False)

    quantity = Column(Integer, nullable=False)

    # Permanently nullable by design, not a migration-in-progress state —
    # webhook-sourced events have no human actor, and NULL is honest here;
    # inventing a synthetic "system" user would muddy a real accountability
    # feature.
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
