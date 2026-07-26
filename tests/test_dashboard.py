# tests/test_dashboard.py

import os

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.user import User

from .utils import create_product, purchase

RECIPES_PAGE = "dashboard/pages/1_Recipes.py"

_FEATURE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "feature_store", "daily_sales.parquet"
)
_FEATURE_SKIP_REASON = "feature store not built — run make features"


def _make_dashboard_user(
    dashboard_db,
    email="dash-user@example.com",
    password="dash-password",  # noqa: S107 -- test fixture value, not a real credential
    role=UserRole.MEMBER,
):
    session = dashboard_db()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name="Dash User",
            role=role,
        )
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
        "role": user.role.value,
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
    assert at.session_state["user"]["role"] == "member"
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


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_admin_sees_admin_ops_section(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    admin = _make_dashboard_user(dashboard_db, email="ops-admin@example.com", role=UserRole.ADMIN)

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, admin)
    at.run()

    assert not at.exception
    assert any("Admin / Ops" in s.value for s in at.subheader)


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_member_does_not_see_admin_ops_section(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    member = _make_dashboard_user(dashboard_db, email="ops-member@example.com")

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, member)
    at.run()

    assert not at.exception
    assert not any("Admin / Ops" in s.value for s in at.subheader)


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_admin_can_trigger_replay(client, admin_actions_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    admin = _make_dashboard_user(
        admin_actions_db, email="ops-replay-admin@example.com", role=UserRole.ADMIN
    )

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, admin)
    at.run()

    checkbox = next(
        c for c in at.checkbox if "rebuilds inventory state for all products" in c.label
    )
    checkbox.check().run()

    button = next(b for b in at.button if b.label == "Rebuild inventory projection")
    button.click().run()

    assert not at.exception
    assert any("Rebuilt state for" in s.value for s in at.success)

    session = admin_actions_db()
    try:
        entry = (
            session.query(AuditLog)
            .filter(AuditLog.action == "replay")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.actor_id == admin.id
    finally:
        session.close()


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_dashboard_admin_can_trigger_export(client, admin_actions_db, export_paths, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    admin = _make_dashboard_user(
        admin_actions_db, email="ops-export-admin@example.com", role=UserRole.ADMIN
    )

    monkeypatch.setattr("dashboard.data.forecast", lambda *a, **k: _fake_forecast_df())

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, admin)
    at.run()

    button = next(b for b in at.button if b.label == "Export inventory events")
    button.click().run()

    assert not at.exception
    assert any("Exported" in s.value for s in at.success)

    session = admin_actions_db()
    try:
        entry = (
            session.query(AuditLog)
            .filter(AuditLog.action == "export")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.actor_id == admin.id
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Recipes / BOM page (dashboard/pages/1_Recipes.py) — no feature-store
# dependency, unlike app.py above, so no _FEATURE_FILE skipif needed.
# ---------------------------------------------------------------------------


def test_recipes_page_renders_without_exception(client, dashboard_db):
    create_product(client, "Burger")
    user = _make_dashboard_user(dashboard_db)

    # load_products()/load_recipe_items() are @st.cache_data'd with no
    # per-test isolation — across separate AppTest runs in the same pytest
    # process, product ids collide (each test's DB restarts autoincrement
    # at 1), so a stale cross-test cache entry can mask this test's real
    # data. Same reason app.py has a manual "Refresh" button.
    st.cache_data.clear()

    at = AppTest.from_file(RECIPES_PAGE)
    _signed_in(at, user)
    at.run()

    assert not at.exception


def test_recipes_page_shows_no_recipe_message_for_new_dish(client, dashboard_db):
    create_product(client, "Burger")
    user = _make_dashboard_user(dashboard_db)

    # load_products()/load_recipe_items() are @st.cache_data'd with no
    # per-test isolation — across separate AppTest runs in the same pytest
    # process, product ids collide (each test's DB restarts autoincrement
    # at 1), so a stale cross-test cache entry can mask this test's real
    # data. Same reason app.py has a manual "Refresh" button.
    st.cache_data.clear()

    at = AppTest.from_file(RECIPES_PAGE)
    _signed_in(at, user)
    at.run()

    assert not at.exception
    assert any("no recipe yet" in i.value for i in at.info)


def test_recipes_page_add_ingredient_then_shows_it(client, dashboard_db):
    dish = create_product(client, "Burger")
    ingredient = create_product(client, "Bun")
    user = _make_dashboard_user(dashboard_db)

    # load_products()/load_recipe_items() are @st.cache_data'd with no
    # per-test isolation — across separate AppTest runs in the same pytest
    # process, product ids collide (each test's DB restarts autoincrement
    # at 1), so a stale cross-test cache entry can mask this test's real
    # data. Same reason app.py has a manual "Refresh" button.
    st.cache_data.clear()

    at = AppTest.from_file(RECIPES_PAGE)
    _signed_in(at, user)
    at.run()

    dish_select = next(s for s in at.selectbox if s.label == "Dish")
    dish_select.select(dish["id"]).run()

    ingredient_select = next(s for s in at.selectbox if s.label == "Ingredient")
    ingredient_select.select(ingredient["id"]).run()

    quantity_input = next(n for n in at.number_input if n.label == "Quantity per dish sold")
    quantity_input.set_value(3).run()

    submit = next(b for b in at.button if b.label == "Add ingredient")
    submit.click().run()

    assert not at.exception
    assert not any("no recipe yet" in i.value for i in at.info)
    assert any("Bun" in md.value for md in at.markdown)
