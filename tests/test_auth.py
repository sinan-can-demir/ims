# tests/test_auth.py

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.core import auth as auth_core
from app.core.auth import create_access_token, require_current_user
from app.core.security import hash_password
from app.main import app
from app.models.user import User


def test_health_is_exempt():
    """Health endpoint must not require auth — Docker HEALTHCHECK depends on it."""
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 200


def test_missing_bearer_token_returns_401(client):
    # `client` is requested (unused directly) so its dependency_overrides
    # side effect — pointing get_db at the test session — is active; this
    # bare TestClient shares the same `app` object but sends no auth header.
    bare_client = TestClient(app, raise_server_exceptions=False)
    response = bare_client.get("/api/inventory/1")
    assert response.status_code == 401


def test_invalid_bearer_token_returns_401(client):
    response = client.get("/api/inventory/1", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


def test_expired_bearer_token_returns_401(client, db):
    user = db.query(User).filter(User.email == "test-client@example.com").first()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now - timedelta(hours=13),
        "exp": now - timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, auth_core._JWT_SECRET, algorithm=auth_core._JWT_ALGORITHM)
    response = client.get("/api/inventory/1", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401


def test_replay_without_token_returns_401(client):
    """
    /api/inventory/replay rebuilds inventory_state from scratch (delete +
    reinsert) — explicit coverage that it's auth-gated like the rest of the
    inventory router, not just implicitly covered by the other cases here.
    """
    bare_client = TestClient(app, raise_server_exceptions=False)
    response = bare_client.post("/api/inventory/replay")
    assert response.status_code == 401


def test_valid_bearer_token_passes_auth(client):
    # No product 999999 — a 404 (not 401) proves auth passed and the
    # request reached the route handler.
    response = client.get("/api/inventory/999999")
    assert response.status_code == 404


def test_deactivated_user_bearer_token_returns_401(client, db):
    user = db.query(User).filter(User.email == "test-client@example.com").first()
    user.is_active = False
    db.commit()

    response = client.get("/api/inventory/1")
    assert response.status_code == 401


def _make_user(db, email, password, is_active=True):
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name="Test User",
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_login_success_returns_bearer_token(client, db):
    _make_user(db, "login@example.com", "correct horse battery")
    response = client.post(
        "/api/auth/login",
        json={"email": "login@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"  # noqa: S105 -- auth scheme label, not a credential
    assert body["access_token"]


def test_login_wrong_password_returns_generic_401(client, db):
    _make_user(db, "login2@example.com", "right-password")
    response = client.post(
        "/api/auth/login",
        json={"email": "login2@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_unknown_email_returns_same_generic_401(client, db):
    """Same message/status as wrong-password — no user-enumeration leak."""
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_deactivated_user_returns_generic_401(client, db):
    _make_user(db, "inactive@example.com", "pw", is_active=False)
    response = client.post(
        "/api/auth/login",
        json={"email": "inactive@example.com", "password": "pw"},
    )
    assert response.status_code == 401


def test_require_current_user_accepts_valid_token(db):
    user = _make_user(db, "valid@example.com", "pw")
    token = create_access_token(user)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    resolved = require_current_user(credentials=credentials, db=db)
    assert resolved.id == user.id


def test_require_current_user_rejects_missing_token(db):
    with pytest.raises(HTTPException) as exc_info:
        require_current_user(credentials=None, db=db)
    assert exc_info.value.status_code == 401


def test_require_current_user_rejects_invalid_token(db):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
    with pytest.raises(HTTPException) as exc_info:
        require_current_user(credentials=credentials, db=db)
    assert exc_info.value.status_code == 401


def test_require_current_user_rejects_expired_token(db):
    user = _make_user(db, "expired@example.com", "pw")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now - timedelta(hours=13),
        "exp": now - timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, auth_core._JWT_SECRET, algorithm=auth_core._JWT_ALGORITHM)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
    with pytest.raises(HTTPException) as exc_info:
        require_current_user(credentials=credentials, db=db)
    assert exc_info.value.status_code == 401


def test_require_current_user_rejects_deactivated_user_token(db):
    """A previously-valid, unexpired token stops working once is_active flips false."""
    user = _make_user(db, "deactivate@example.com", "pw")
    token = create_access_token(user)
    user.is_active = False
    db.commit()

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        require_current_user(credentials=credentials, db=db)
    assert exc_info.value.status_code == 401
