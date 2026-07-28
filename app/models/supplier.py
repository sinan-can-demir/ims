from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    # Composite-FK target for purchase_orders — see Product's identical
    # comment (Epoch 10).
    __table_args__ = (UniqueConstraint("organization_id", "id", name="uq_suppliers_org_id"),)

    id = Column(Integer, primary_key=True, index=True)

    # server_default="1" kept permanently — see Product's identical
    # comment (Epoch 10) for why.
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    name = Column(String, nullable=False)

    contact_email = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
