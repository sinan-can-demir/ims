from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    # Composite-FK target for purchase_orders.created_by_id,
    # inventory_events.created_by_id, audit_log.actor_id (Epoch 10). One
    # org per user (a scalar column, not a join table) — nothing in this
    # codebase models multi-org-per-user, and email stays globally unique
    # below (no org-selection step at login), so a single org per account
    # is the only self-consistent shape; see ROADMAP.md's EPOCH 10 section.
    __table_args__ = (UniqueConstraint("organization_id", "id", name="uq_users_org_id"),)

    id = Column(Integer, primary_key=True, index=True)

    # server_default="1" kept permanently, same idiom as is_active/role
    # below — a safety net for any User(...) construction that doesn't
    # explicitly pass organization_id, even though scripts/create_user.py
    # (this PR) and every route (a later Epoch 10 PR) do.
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    email = Column(String, unique=True, nullable=False, index=True)

    password_hash = Column(String, nullable=False)

    display_name = Column(String, nullable=False)

    # Deactivate without deleting — keeps FK integrity for historical
    # InventoryEvent.created_by_id references to this user.
    is_active = Column(Boolean, nullable=False, server_default="true")

    # Defaults every existing/new row to the least-privileged role, same
    # server_default-for-safe-backfill idiom as is_active — a migration can
    # never silently grant elevated access. Admins are explicit: --role admin
    # at creation (scripts/create_user.py) or promotion via
    # scripts/set_user_role.py.
    #
    # values_callable stores UserRole.value ("admin"/"member") rather than
    # SQLAlchemy's default of the member .name ("ADMIN"/"MEMBER") — matches
    # the lowercase values the migration's Postgres enum type was created
    # with, and what the API/CLI pass around as plain strings.
    role = Column(
        Enum(
            UserRole,
            name="user_role_enum",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        server_default=UserRole.MEMBER.value,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Account-level brute-force lockout (see auth_service.authenticate_user)
    # — a defense-in-depth layer distinct from the API's IP-based
    # slowapi rate limiting (app/core/rate_limit.py). Needed because
    # dashboard/auth.py calls authenticate_user() directly, in-process, with
    # no HTTP request/IP to key a rate limit off of; this column-based
    # counter protects that path too, for free, since both surfaces share
    # this one function.
    failed_login_attempts = Column(Integer, nullable=False, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
