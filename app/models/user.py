from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

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
