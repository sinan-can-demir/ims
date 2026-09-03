# tests/conftest.py

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import create_access_token
from app.core.security import hash_password
from app.database import Base, get_db
from app.main import app
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    engine = create_engine(TEST_DATABASE_URL)
else:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "postgres: requires a real Postgres DB — set TEST_DATABASE_URL to run"
    )


def pytest_collection_modifyitems(config, items):
    if not TEST_DATABASE_URL:
        skip = pytest.mark.skip(reason="requires Postgres — set TEST_DATABASE_URL env var")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    # Bootstrap org (id=1), same as the real Epoch 10 migration's seed row
    # — every table with organization_id is a NOT NULL FK to this, so
    # anything the test suite creates needs it to exist first.
    # webhook_secret is NOT NULL (see app/models/organization.py) — any
    # fixed test value works, since most tests never touch the webhook
    # routes; tests that do (tests/test_webhook.py,
    # tests/test_multi_tenancy.py) override it via utils.set_webhook_secret.
    session.add(
        Organization(
            id=1,
            name="Default Organization",
            webhook_secret="test-bootstrap-secret",  # noqa: S106 -- test fixture value, not a real credential
        )
    )
    session.commit()
    if TEST_DATABASE_URL:
        # Same resync the real migration does (see
        # 6eb479a8a33c_add_organizations_table.py) and for the same
        # reason: an explicit id=1 insert doesn't advance Postgres's
        # sequence, so the next auto-assigned insert (e.g. the
        # `second_org` fixture) would collide on id=1 without this.
        # SQLite has no equivalent sequence object to resync — its
        # rowid-based autoincrement doesn't have this failure mode, so
        # this is a no-op there, guarded by TEST_DATABASE_URL like the
        # engine selection above.
        session.execute(text("SELECT setval('organizations_id_seq', 1)"))
        session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def dashboard_db(db, monkeypatch):
    """
    Points the dashboard's directly-imported app.database.SessionLocal at
    this same test engine. The dashboard doesn't use FastAPI's
    Depends(get_db) — it calls SessionLocal() itself — so
    dependency_overrides (as the `client` fixture uses) doesn't apply here;
    patching the attribute that `from app.database import SessionLocal`
    resolves at script-execution time is what actually takes effect.

    Depends on `db` (rather than managing its own create_all/drop_all)
    specifically so pytest's fixture-teardown order — reverse of setup —
    guarantees `db`'s session.close() runs before `db`'s own drop_all().
    Under SQLite's single shared StaticPool connection this never
    mattered, but under a real Postgres backend (set TEST_DATABASE_URL),
    every write ends with `db.commit(); db.refresh(x)` — refresh reopens
    an implicit transaction that holds a lock until the session closes.
    A test using both `client` (which holds `db` open for the whole test)
    and this fixture would previously call drop_all() here *before*
    `db`'s session ever closed — DROP TABLE blocking forever on a lock
    that only `db`'s own finalizer would release, deadlocking every CI
    run that actually exercised this combination (previously masked
    because every prior dashboard test happened to skip under CI's
    missing feature-store file).
    """
    monkeypatch.setattr("app.database.SessionLocal", TestingSessionLocal)
    yield TestingSessionLocal


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    # Every /api route now requires a valid bearer token (require_current_user)
    # — create a real user in the test db and mint one, so existing tests
    # that just want "an authenticated client" don't each need to do this.
    user = User(
        email="test-client@example.com",
        password_hash=hash_password("test-client-password"),
        display_name="Test Client",
        organization_id=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(scope="function")
def admin_client(db):
    """
    Separate fixture rather than parametrizing `client` on role — `client`
    is used throughout the suite as "an authenticated user," and most of
    those call sites don't care about role; keeping it MEMBER by default
    avoids touching every existing test that consumes it.
    """

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    user = User(
        email="test-admin@example.com",
        password_hash=hash_password("test-admin-password"),
        display_name="Test Admin",
        role=UserRole.ADMIN,
        organization_id=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def second_org(db):
    """
    A real 2nd organization for the Epoch 10 cross-org isolation suite —
    every org-scoped table's organization_id is a NOT NULL FK, so a
    "different org" test fixture needs an actual Organization row to point
    at, same as org 1's bootstrap row the `db` fixture itself creates.
    """
    org = Organization(
        name="Second Org",
        webhook_secret="test-second-org-secret",  # noqa: S106 -- test fixture value, not a real credential
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture(scope="function")
def client_org2(db, second_org):
    """
    Same shape as `client`, authenticated as a user in `second_org` instead
    of the bootstrap org — cross-org isolation tests use this alongside
    `client`/`admin_client` to prove org 1's data is invisible to org 2's
    user, and vice versa.
    """

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    user = User(
        email="test-client-org2@example.com",
        password_hash=hash_password("test-client-org2-password"),
        display_name="Test Client Org2",
        organization_id=second_org.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(scope="function")
def admin_client_org2(db, second_org):
    """Same shape as `admin_client`, in `second_org` instead of org 1."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    user = User(
        email="test-admin-org2@example.com",
        password_hash=hash_password("test-admin-org2-password"),
        display_name="Test Admin Org2",
        role=UserRole.ADMIN,
        organization_id=second_org.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def set_user_role_db(dashboard_db, monkeypatch):
    """
    scripts/set_user_role.py does `from app.database import SessionLocal`
    at its own import time, which binds an independent name in that
    module's namespace — patching app.database.SessionLocal (what
    dashboard_db does) never reaches it. Patch the name where it's
    actually looked up: scripts.set_user_role's own module namespace.
    """
    monkeypatch.setattr("scripts.set_user_role.SessionLocal", dashboard_db)
    return dashboard_db


@pytest.fixture
def create_organization_db(dashboard_db, monkeypatch):
    """Same independent-name patch as set_user_role_db, for scripts/create_organization.py."""
    monkeypatch.setattr("scripts.create_organization.SessionLocal", dashboard_db)
    return dashboard_db


@pytest.fixture
def rotate_webhook_secret_db(dashboard_db, monkeypatch):
    """Same independent-name patch as set_user_role_db, for scripts/rotate_webhook_secret.py."""
    monkeypatch.setattr("scripts.rotate_webhook_secret.SessionLocal", dashboard_db)
    return dashboard_db


@pytest.fixture
def admin_actions_db(dashboard_db, monkeypatch):
    """
    dashboard/admin_actions.py does `from app.database import
    SessionLocal` at its own import time — same independent-name issue
    as set_user_role_db above, patched the same way.
    """
    monkeypatch.setattr("dashboard.admin_actions.SessionLocal", dashboard_db)
    return dashboard_db


@pytest.fixture
def export_paths(tmp_path):
    events_root = tmp_path / "inventory_events"
    checkpoint = tmp_path / "checkpoints.json"
    with (
        patch("app.services.export_service.INVENTORY_EVENTS_ROOT", events_root),
        patch("app.services.export_service.CHECKPOINT_FILE", checkpoint),
    ):
        yield events_root, checkpoint


@pytest.fixture
def warehouse_paths(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    events_root = tmp_path / "inventory_events"
    with (
        patch("app.services.warehouse_service.WAREHOUSE_ROOT", warehouse_root),
        patch("app.services.warehouse_service.INVENTORY_EVENTS_ROOT", events_root),
    ):
        yield warehouse_root
