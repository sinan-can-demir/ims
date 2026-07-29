from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import PurchaseOrderStatus


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    # UNIQUE(organization_id, id) — purchase_orders is itself a
    # composite-FK parent for purchase_order_lines (next Epoch 10 PR), same
    # reason products/suppliers/users got this in PR 2.
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_purchase_orders_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "supplier_id"],
            ["suppliers.organization_id", "suppliers.id"],
            name="fk_purchase_orders_org_supplier",
        ),
        # created_by_id is NOT NULL here (unlike inventory_events), so
        # MATCH SIMPLE vs MATCH FULL is moot in practice — kept unspecified
        # for consistency with the other composite FKs in 688eb809961b.
        ForeignKeyConstraint(
            ["organization_id", "created_by_id"],
            ["users.organization_id", "users.id"],
            name="fk_purchase_orders_org_created_by",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Backfilled via suppliers.organization_id (see 688eb809961b).
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

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
