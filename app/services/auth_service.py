from sqlalchemy.orm import Session

from app.core.exceptions import InvalidCredentialsError, RegistrationClosedError
from app.core.security import hash_password, verify_password
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from app.services.audit_service import log_action


def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    Looks up a user by email and verifies their password.

    Raises the same InvalidCredentialsError for "no such user" and "wrong
    password" — a distinct error per case would let an attacker enumerate
    which emails have accounts. The audit log, unlike the response, does
    distinguish them: actor_id is the found user's id when one exists
    (wrong password, deactivated account), or None for a genuinely unknown
    email, since there's no user row to reference.
    """
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(password, user.password_hash):
        log_action(db, user.id if user else None, "login_failed", detail=email)
        raise InvalidCredentialsError()
    if not user.is_active:
        log_action(db, user.id, "login_failed", detail=email)
        raise InvalidCredentialsError()
    return user


def _org1_has_users(db: Session) -> bool:
    return db.query(User).filter(User.organization_id == 1).count() > 0


def needs_registration(db: Session) -> bool:
    """
    Read-only bootstrap check for the desktop wizard (#192) — whether to
    show a "create the first account" form at all, before any user input
    exists to submit. Not itself a race guard (no locking): a concurrent
    registration between this check and the wizard's later POST just means
    that POST hits register_first_user()'s own with_for_update() lock and
    gets RegistrationClosedError, same as any other late caller. This
    function only ever gates what the UI *shows*, not what's allowed to
    happen — the real security boundary stays register_first_user()'s lock.
    """
    return not _org1_has_users(db)


def register_first_user(db: Session, email: str, password: str, display_name: str) -> User:
    """
    Bootstrap-only account creation for organization_id=1 — the desktop
    installer's GUI equivalent of scripts/create_user.py, which stays
    CLI/getpass-only (see SECURITY.md). Only succeeds while org 1 has zero
    users; hardcodes role=admin (same precedent as scripts/ims.py's
    _create_first_account()) and organization_id=1 — no client-settable
    role or org, matching #189.

    Race-safe via with_for_update() on organization 1's own row, not a
    naive count-then-insert — same row-locking idiom already used for
    idempotency-critical writes in app/services/inventory_service.py.
    Locking a *user* row here wouldn't work: the whole point is that org
    1 has zero of them, and FOR UPDATE on a query matching no rows
    acquires no lock at all. The organization row always exists exactly
    once, so it's the only reliable thing to serialize concurrent
    registration attempts on. Two concurrent calls block on this same
    lock; whichever commits first "wins," and the second sees the
    now-existing user under the lock and rejects — no race window.
    """
    db.query(Organization).filter(Organization.id == 1).with_for_update().first()

    if _org1_has_users(db):
        raise RegistrationClosedError()

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=UserRole.ADMIN.value,
        organization_id=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
