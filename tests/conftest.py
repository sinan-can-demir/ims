# tests/conftest.py

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import create_access_token
from app.core.security import hash_password
from app.database import Base, get_db
from app.main import app
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
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def dashboard_db(monkeypatch):
    """
    Points the dashboard's directly-imported app.database.SessionLocal at
    this same StaticPool test engine. The dashboard doesn't use FastAPI's
    Depends(get_db) — it calls SessionLocal() itself — so
    dependency_overrides (as the `client` fixture uses) doesn't apply here;
    patching the attribute that `from app.database import SessionLocal`
    resolves at script-execution time is what actually takes effect.
    """
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr("app.database.SessionLocal", TestingSessionLocal)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)


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
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


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
