from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)

    # Backfilled directly to the bootstrap org (id=1), not via actor_id —
    # actor_id is nullable (failed logins against unknown emails have no
    # user row), so there's no reliable parent to backfill through for
    # those rows. No UniqueConstraint(organization_id, id) here — unlike
    # products/suppliers/users, nothing composite-FKs to audit_log as a
    # parent, it's only ever a child (Epoch 10). server_default="1" kept
    # permanently for the pre-Epoch-10 backfill and as a DB-level safety
    # net — audit_service.log_action() itself requires organization_id
    # explicitly at every call site now (no Python-level default), after
    # a real misattribution bug where several call sites silently fell
    # through to a `organization_id: int = 1` default that used to exist
    # there instead.
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    # Nullable — a failed login against an unknown email has no user row
    # to reference. NULL is honest there, same reasoning as
    # InventoryEvent.created_by_id: a synthetic "system" actor would
    # muddy a real accountability feature.
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    action = Column(String, nullable=False, index=True)

    detail = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
