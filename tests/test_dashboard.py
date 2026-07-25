# tests/test_dashboard.py

import os

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app.core.security import hash_password
from app.models.user import User

from .utils import create_product, purchase

_FEATURE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "feature_store", "daily_sales.parquet"
)
_FEATURE_SKIP_REASON = "feature store not built — run make features"


def _make_dashboard_user(
    dashboard_db,
    email="dash-user@example.com",
    password="dash-password",  # noqa: S107 -- test fixture value, not a real credential
):
    session = dashboard_db()
    try:
        user = User(email=email, password_hash=hash_password(password), display_name="Dash User")
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def _signed_in(at: AppTest, user: User) -> None:
    """
    Pre-seeds session_state as if login_form() had already run — mirrors
    conftest.py's `client` fixture pattern of authenticating once as a
    fixture concern rather than re-driving a full login in every test
    that just wants to exercise gated content.
    """
    at.session_state["user"] = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
    }


def _fake_forecast_df():
    return pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [15.0] * 7,
            "yhat_lower": [10.0] * 7,
            "yhat_upper": [20.0] * 7,
        }
    )


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_renders_without_exception(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_shows_inventory_metric(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert "Current Inventory" in metric_labels


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_blocks_unauthenticated_visitor(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    at.run()

    assert not at.exception
    # Login form shown instead — gated content never rendered.
    assert any("Sign in" in b.value for b in at.subheader)
    assert not at.metric


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_login_success_unlocks_content(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    _make_dashboard_user(
        dashboard_db,
        email="login-flow@example.com",
        password="correct-password",  # noqa: S106 -- test fixture value, not a real credential
    )

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    at.run()

    at.text_input[0].input("login-flow@example.com")
    at.text_input[1].input("correct-password")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["user"]["email"] == "login-flow@example.com"
    metric_labels = [m.label for m in at.metric]
    assert "Current Inventory" in metric_labels


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_login_failure_shows_error(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    _make_dashboard_user(
        dashboard_db,
        email="login-fail@example.com",
        password="correct-password",  # noqa: S106 -- test fixture value, not a real credential
    )

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    at.run()

    at.text_input[0].input("login-fail@example.com")
    at.text_input[1].input("wrong-password")
    at.button[0].click().run()

    assert not at.exception
    assert "user" not in at.session_state
    assert any("Invalid email or password" in e.value for e in at.error)
