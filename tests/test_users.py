# tests/test_users.py

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password, verify_password
from app.models.enums import UserRole
from app.models.user import User


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_over_72_bytes_rejected():
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("x" * 73)


def test_verify_over_72_bytes_returns_false_not_raises():
    hashed = hash_password("a normal password")
    assert not verify_password("x" * 73, hashed)


def test_duplicate_email_rejected(db):
    db.add(
        User(
            email="dupe@example.com",
            password_hash=hash_password("password1"),
            display_name="First",
        )
    )
    db.commit()

    db.add(
        User(
            email="dupe@example.com",
            password_hash=hash_password("password2"),
            display_name="Second",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_user_defaults_to_active(db):
    user = User(
        email="active@example.com",
        password_hash=hash_password("password1"),
        display_name="Active User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.is_active is True


def test_user_defaults_to_member(db):
    user = User(
        email="member@example.com",
        password_hash=hash_password("password1"),
        display_name="Member User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.role == UserRole.MEMBER
