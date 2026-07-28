from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    # Per-org webhook signing secret (see app/core/auth.py's
    # require_webhook_signature, wired up in Epoch 10 PR 12) — nullable
    # mirrors today's single global WEBHOOK_SECRET's "unset = signature
    # verification disabled" shape, per-org instead of per-deployment.
    webhook_secret = Column(String, nullable=True)

    # Deactivate-without-delete, same idiom as User.is_active — preserves
    # FK integrity for every row this org's users/products/etc. created,
    # rather than cascading a delete through the entire schema.
    is_active = Column(Boolean, nullable=False, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
