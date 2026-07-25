from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)

    # Nullable — a failed login against an unknown email has no user row
    # to reference. NULL is honest there, same reasoning as
    # InventoryEvent.created_by_id: a synthetic "system" actor would
    # muddy a real accountability feature.
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    action = Column(String, nullable=False, index=True)

    detail = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
