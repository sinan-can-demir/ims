# tests/test_auth.py

import threading
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.core import auth as auth_core
from app.core.auth import (
    create_access_token,
    get_current_org_id,
    require_current_user,
    require_role,
)
from app.core.exceptions import RegistrationClosedError
from app.core.security import hash_password
from app.database import get_db
from app.main import app
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import register_first_user

from .conftest import TestingSessionLocal


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


def _make_user(db, email, password, is_active=True, role=UserRole.MEMBER):
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name="Test User",
        is_active=is_active,
        role=role,
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


def test_require_role_accepts_matching_role(db):
    admin = _make_user(db, "admin@example.com", "pw", role=UserRole.ADMIN)
    check = require_role(UserRole.ADMIN)
    resolved = check(current_user=admin)
    assert resolved.id == admin.id


def test_require_role_rejects_non_matching_role(db):
    member = _make_user(db, "member-role@example.com", "pw", role=UserRole.MEMBER)
    check = require_role(UserRole.ADMIN)
    with pytest.raises(HTTPException) as exc_info:
        check(current_user=member)
    assert exc_info.value.status_code == 403


def test_require_role_promotion_takes_effect_without_new_token(db):
    """
    No role claim in the JWT (see create_access_token) — a role change
    takes effect on the very next request with the same, still-unexpired
    token, same live-DB-recheck convention as is_active deactivation.
    """
    user = _make_user(db, "promote@example.com", "pw", role=UserRole.MEMBER)
    token = create_access_token(user)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    check = require_role(UserRole.ADMIN)
    resolved = require_current_user(credentials=credentials, db=db)
    with pytest.raises(HTTPException) as exc_info:
        check(current_user=resolved)
    assert exc_info.value.status_code == 403

    user.role = UserRole.ADMIN
    db.commit()

    resolved = require_current_user(credentials=credentials, db=db)
    assert check(current_user=resolved).id == user.id


def test_get_current_org_id_returns_users_organization_id(db):
    user = _make_user(db, "org-check@example.com", "pw")
    assert get_current_org_id(current_user=user) == user.organization_id == 1


def test_get_current_org_id_reflects_live_row_without_new_token(db, second_org):
    """
    No org claim in the JWT (see create_access_token) — moving a user to a
    different org takes effect on the very next request with the same,
    still-unexpired token, same live-DB-recheck convention as
    role/is_active above.
    """
    user = _make_user(db, "org-move@example.com", "pw")
    token = create_access_token(user)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    resolved = require_current_user(credentials=credentials, db=db)
    assert get_current_org_id(current_user=resolved) == 1

    user.organization_id = second_org.id
    db.commit()

    resolved = require_current_user(credentials=credentials, db=db)
    assert get_current_org_id(current_user=resolved) == second_org.id


def _unauthenticated_client(db):
    """
    A TestClient bound to the test db but with no bearer token and no
    pre-created user — unlike the `client`/`admin_client` fixtures, which
    both insert a user into org 1 as a side effect and would break the
    "zero users exist" precondition these register() tests depend on.
    """

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False)


def test_register_first_user_succeeds(db):
    response = _unauthenticated_client(db).post(
        "/api/auth/register",
        json={
            "email": "founder@example.com",
            "password": "correct horse battery",
            "display_name": "Founder",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "founder@example.com"
    assert body["role"] == "admin"
    assert body["organization_id"] == 1


def test_register_second_call_rejected(db):
    client = _unauthenticated_client(db)
    first = client.post(
        "/api/auth/register",
        json={"email": "first@example.com", "password": "pw", "display_name": "First"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={"email": "second@example.com", "password": "pw", "display_name": "Second"},
    )
    assert second.status_code == 409

    assert db.query(User).filter(User.organization_id == 1).count() == 1


def test_register_then_login_round_trip(db):
    client = _unauthenticated_client(db)
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "roundtrip@example.com",
            "password": "correct horse battery",
            "display_name": "Round Trip",
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"email": "roundtrip@example.com", "password": "correct horse battery"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["access_token"]


def test_bootstrap_status_true_when_no_users(db):
    response = _unauthenticated_client(db).get("/api/auth/bootstrap-status")
    assert response.status_code == 200
    assert response.json() == {"needs_registration": True}


def test_bootstrap_status_false_after_registration(db):
    client = _unauthenticated_client(db)
    register_response = client.post(
        "/api/auth/register",
        json={"email": "bootstrap@example.com", "password": "pw", "display_name": "Bootstrap"},
    )
    assert register_response.status_code == 201

    response = client.get("/api/auth/bootstrap-status")
    assert response.status_code == 200
    assert response.json() == {"needs_registration": False}


@pytest.mark.postgres
def test_register_concurrent_requests_only_one_succeeds(db):
    """
    Real concurrency coverage for the with_for_update() lock in
    register_first_user (see #189) — not just the sequential
    already-registered case above. N threads race to register the first
    account for org 1, each on its own real DB connection (a fresh
    TestingSessionLocal() per thread, matching
    test_idempotency.py's established pattern — a single shared Session
    isn't safe for concurrent use and wouldn't exercise real
    connection-level row locking). Exactly one must succeed.
    """
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    results = [None] * thread_count

    def _worker(i):
        session = TestingSessionLocal()
        try:
            barrier.wait()  # maximize real overlap on the row-lock window
            try:
                user = register_first_user(session, f"racer{i}@example.com", "pw", f"Racer {i}")
                results[i] = ("ok", user.id)
            except RegistrationClosedError:
                results[i] = ("rejected", None)
        finally:
            session.close()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    outcomes = [r[0] for r in results]
    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == thread_count - 1

    db.expire_all()
    assert db.query(User).filter(User.organization_id == 1).count() == 1
