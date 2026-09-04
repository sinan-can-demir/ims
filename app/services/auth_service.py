from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import InvalidCredentialsError, RegistrationClosedError
from app.core.security import hash_password, verify_password_or_dummy
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from app.services.audit_service import log_action

# Account-level brute-force lockout — see User.failed_login_attempts'
# docstring for why this exists alongside the API's IP-based rate limiting.
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION = timedelta(minutes=15)


def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    Looks up a user by email and verifies their password.

    Raises the same InvalidCredentialsError for "no such user", "wrong
    password", and "locked out" — a distinct error per case would let an
    attacker enumerate which emails have accounts (or which are currently
    locked, which is just as much of a leak). The audit log, unlike the
    response, does distinguish them: actor_id is the found user's id when
    one exists (wrong password, deactivated account, locked out), or None
    for a genuinely unknown email, since there's no user row to reference.

    Exactly one bcrypt call happens on every path through this function
    (verify_password_or_dummy, called unconditionally right after the
    lookup, before any branch) — closing a timing side-channel: unknown
    email and locked-out account used to short-circuit past bcrypt
    entirely (~100ms-1s depending on hardware/bcrypt cost, vs. a few ms
    for the DB-only branches), so response latency alone told an attacker
    which case they'd hit without needing the response body.
    """
    # with_for_update() serializes every branch below (locked check,
    # attempt-counter increment, lockout-set, success-reset) against
    # concurrent login attempts for the same email — same idiom as
    # register_first_user()'s row lock, for the identical race: without
    # it, N concurrent wrong-password requests can all read the same
    # failed_login_attempts value before any of them commits an
    # increment, undercounting the streak and letting an attacker who
    # fires requests in parallel dodge the lockout threshold entirely.
    user = db.query(User).filter(User.email == email).with_for_update().first()

    # Unconditional and first, before any branch below reads or acts on
    # it — see the docstring above. Runs even when user is None or the
    # account is locked, both of which used to skip bcrypt entirely.
    password_ok = verify_password_or_dummy(password, user.password_hash if user else None)

    # Still-locked check only — an *expired* lockout is left as-is here
    # (not proactively cleared) so a wrong attempt right after expiry still
    # counts against the same streak instead of silently granting a fresh
    # set of attempts; only a successful login below resets the streak.
    if (
        user is not None
        and user.locked_until is not None
        and user.locked_until > datetime.now(timezone.utc)
    ):
        # log_action() commits internally (see its own docstring) — that
        # commit is also what releases this row's FOR UPDATE lock.
        log_action(db, user.id, "login_failed", organization_id=user.organization_id, detail=email)
        raise InvalidCredentialsError()

    if user is None or not password_ok:
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= _MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + _LOCKOUT_DURATION
        # The increment above rides along in log_action()'s own commit.
        # A genuinely unknown email has no user row, and therefore no
        # real org to attribute this to — organization_id=1 here is a
        # deliberate fallback, not a missed value (same category as the
        # export call site in app/api/inventory.py).
        log_action(
            db,
            user.id if user else None,
            "login_failed",
            organization_id=user.organization_id if user else 1,
            detail=email,
        )
        raise InvalidCredentialsError()

    if not user.is_active:
        log_action(db, user.id, "login_failed", organization_id=user.organization_id, detail=email)
        raise InvalidCredentialsError()

    # No log_action() call on the success path to ride a commit on —
    # commit unconditionally so the FOR UPDATE lock is always released
    # here rather than left dangling until the caller's session closes.
    # db.commit() expires user's attributes (expire_on_commit default);
    # both callers (app/api/auth.py, dashboard/auth.py) read user.id/
    # .email/.role/etc. *after* closing this same db session, so those
    # attributes must be refreshed back in while the session is still
    # open — same as register_first_user()'s existing db.refresh() below.
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
    db.commit()
    db.refresh(user)

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
