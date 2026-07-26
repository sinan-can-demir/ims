from enum import Enum


class EventType(str, Enum):
    """
    Enumeration for inventory event types.
    """

    PURCHASE = "PURCHASE"
    SALE = "SALE"
    DAMAGE = "DAMAGE"
    ADJUSTMENT = "ADJUSTMENT"
    RETURN = "RETURN"


class UserRole(str, Enum):
    """
    Two roles only, by design — the only concrete admin-gated operations
    today (replay, export) need exactly a can/cannot distinction. See
    ROADMAP.md's RBAC epoch for the reasoning; add a third value here plus
    a migration if a real third-tier need shows up.
    """

    ADMIN = "admin"
    MEMBER = "member"
