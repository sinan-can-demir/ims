from sqlalchemy.orm import Session

from app.core.exceptions import InvalidCredentialsError
from app.core.security import verify_password
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
