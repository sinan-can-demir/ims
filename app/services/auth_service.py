from sqlalchemy.orm import Session

from app.core.exceptions import InvalidCredentialsError
from app.core.security import verify_password
from app.models.user import User


def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    Looks up a user by email and verifies their password.

    Raises the same InvalidCredentialsError for "no such user" and "wrong
    password" — a distinct error per case would let an attacker enumerate
    which emails have accounts.
    """
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise InvalidCredentialsError()
    return user
