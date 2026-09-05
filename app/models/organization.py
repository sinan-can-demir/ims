from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    # Per-org webhook signing secret (see app/core/auth.py's
    # require_webhook_signature, wired up in Epoch 10 PR 12). Every org is
    # provisioned with a real random secret at creation time
    # (scripts/create_organization.py) — NOT NULL, not nullable, since a
    # NULL value used to mean "signature verification disabled" and that
    # was silently true for every org (the provisioning path never set
    # it). See the migration that backfilled existing rows before this
    # constraint landed.
    webhook_secret = Column(String, nullable=False)

    # Deactivate-without-delete, same idiom as User.is_active — preserves
    # FK integrity for every row this org's users/products/etc. created,
    # rather than cascading a delete through the entire schema.
    is_active = Column(Boolean, nullable=False, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Square POS connector (ROADMAP.md's "Food Cost Visibility" Phase 3).
    # All nullable -- NULL means "not connected to Square," the normal
    # state for every org until they go through the OAuth flow, unlike
    # webhook_secret above (which every org gets unconditionally at
    # creation). Stored in plaintext, same as webhook_secret -- this
    # matches the existing security posture of this single-shared-DB-role
    # codebase rather than introducing a new at-rest-encryption pattern
    # unilaterally; flagged here explicitly as a real, known limitation
    # to revisit before any real (non-sandbox) deployment uses this.
    square_access_token = Column(String, nullable=True)
    square_refresh_token = Column(String, nullable=True)
    # Square access tokens expire ~30 days after issue; the sync job
    # checks this before every run and refreshes if close to expiring
    # (see scripts/sync_square_sales.py once it exists).
    square_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    # Square's own merchant id -- needed to scope API calls once
    # connected, distinct from IMS's own organization_id.
    square_merchant_id = Column(String, nullable=True)
