# tests/test_dashboard.py

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.user import User

from .utils import create_product, purchase

RECIPES_PAGE = "dashboard/views/recipes.py"
PURCHASE_ORDERS_PAGE = "dashboard/views/purchase_orders.py"
FLEET_OVERVIEW_PAGE = "dashboard/views/fleet_overview.py"


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
        "organization_id": user.organization_id,
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


def _mock_forecast(monkeypatch, fn=None):
    """
    Mocks both call sites that reach forecast_service.forecast(): the
    dashboard's own load_forecast() (dashboard.data.forecast) and
    restock_service.get_restock_recommendation()'s separate import
    (app.services.restock_service.forecast) — see the fix in
    fix(tests): mock restock_service.forecast, not just
    dashboard.data.forecast for why both are required.
    """
    forecast_fn = fn or (lambda *a, **k: _fake_forecast_df())
    monkeypatch.setattr("dashboard.data.forecast", forecast_fn)
    monkeypatch.setattr("app.services.restock_service.forecast", forecast_fn)


def test_dashboard_renders_without_exception(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception


def test_dashboard_shows_inventory_metric(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert "Current Inventory" in metric_labels


def test_dashboard_blocks_unauthenticated_visitor(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    at.run()

    assert not at.exception
    # Login form shown instead — gated content never rendered.
    assert any("Sign in" in b.value for b in at.subheader)
    assert not at.metric


def test_dashboard_login_success_unlocks_content(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    _make_dashboard_user(
        dashboard_db,
        email="login-flow@example.com",
        password="correct-password",  # noqa: S106 -- test fixture value, not a real credential
    )

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    at.run()

    at.text_input[0].input("login-flow@example.com")
    at.text_input[1].input("correct-password")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["user"]["email"] == "login-flow@example.com"
    assert at.session_state["user"]["role"] == "member"
    assert at.session_state["user"]["organization_id"] == 1
    metric_labels = [m.label for m in at.metric]
    assert "Current Inventory" in metric_labels


def test_dashboard_login_failure_shows_error(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    _make_dashboard_user(
        dashboard_db,
        email="login-fail@example.com",
        password="correct-password",  # noqa: S106 -- test fixture value, not a real credential
    )

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    at.run()

    at.text_input[0].input("login-fail@example.com")
    at.text_input[1].input("wrong-password")
    at.button[0].click().run()

    assert not at.exception
    assert "user" not in at.session_state
    assert any("Invalid email or password" in e.value for e in at.error)


def test_dashboard_admin_sees_admin_ops_section(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    admin = _make_dashboard_user(dashboard_db, email="ops-admin@example.com", role=UserRole.ADMIN)

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, admin)
    at.run()

    assert not at.exception
    assert any("Admin / Ops" in s.value for s in at.subheader)


def test_dashboard_member_does_not_see_admin_ops_section(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    member = _make_dashboard_user(dashboard_db, email="ops-member@example.com")

    _mock_forecast(monkeypatch)

    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, member)
    at.run()

    assert not at.exception
    assert not any("Admin / Ops" in s.value for s in at.subheader)


def test_dashboard_admin_can_trigger_replay(client, admin_actions_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    admin = _make_dashboard_user(
        admin_actions_db, email="ops-replay-admin@example.com", role=UserRole.ADMIN
    )

    _mock_forecast(monkeypatch)

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


def test_dashboard_admin_can_trigger_export(client, admin_actions_db, export_paths, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    admin = _make_dashboard_user(
        admin_actions_db, email="ops-export-admin@example.com", role=UserRole.ADMIN
    )

    _mock_forecast(monkeypatch)

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
# Purchase Orders page (dashboard/views/purchase_orders.py), routed via
# st.navigation() but tested standalone via AppTest.from_file() — the
# page no longer calls st.set_page_config()/require_login() as its real
# gate (that moved to dashboard/app.py, see #69), so running it directly
# with a pre-seeded session_state works the same as before.
# ---------------------------------------------------------------------------


def test_purchase_orders_page_renders_without_exception(client, dashboard_db):
    create_product(client, "Flour")
    user = _make_dashboard_user(dashboard_db)

    st.cache_data.clear()
    at = AppTest.from_file(PURCHASE_ORDERS_PAGE)
    _signed_in(at, user)
    at.run()

    assert not at.exception


# ---------------------------------------------------------------------------
# Recipes / BOM page (dashboard/views/recipes.py) — same standalone
# AppTest pattern as Purchase Orders above.
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


def test_purchase_orders_page_create_manual_draft_and_submit(client, dashboard_db):
    flour = create_product(client, "Flour")
    user = _make_dashboard_user(dashboard_db)

    supplier_resp = client.post("/api/suppliers", json={"name": "Acme Foods"})
    assert supplier_resp.status_code == 201

    st.cache_data.clear()
    at = AppTest.from_file(PURCHASE_ORDERS_PAGE)
    _signed_in(at, user)
    at.run()
    assert not at.exception

    product_select = next(s for s in at.selectbox if s.label == "Product (manual)")
    product_select.select(flour["id"]).run()

    quantity_input = next(n for n in at.number_input if n.label == "Quantity")
    quantity_input.set_value(15).run()

    create_button = next(b for b in at.button if b.label == "Create draft")
    create_button.click().run()

    assert not at.exception
    assert any("Draft purchase order created" in s.value for s in at.success)

    submit_button = next(b for b in at.button if b.label == "Submit purchase order")
    submit_button.click().run()

    assert not at.exception
    assert any("SUBMITTED" in e.label for e in at.expander)


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


# ---------------------------------------------------------------------------
# Product Detail page enhancements (issue #70): forecast horizon slider,
# safety_stock/days_of_stock_remaining KPI tiles, event-type filter +
# pagination on the event history table.
# ---------------------------------------------------------------------------


def test_dashboard_shows_safety_stock_and_days_of_stock_metrics(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    # load_products() etc. are @st.cache_data'd with no per-test isolation
    # — see the Recipes/Purchase Orders section above for why this matters.
    st.cache_data.clear()
    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert "Safety Stock" in metric_labels
    assert "Days of Stock Remaining" in metric_labels


def test_dashboard_forecast_horizon_slider_changes_forecast_days(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    requested_days = []

    def fake_forecast(product_id, days=7):
        requested_days.append(days)
        return _fake_forecast_df()

    _mock_forecast(monkeypatch, fn=fake_forecast)

    st.cache_data.clear()
    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception
    assert 7 in requested_days  # default horizon on first render

    slider = next(s for s in at.slider if s.label == "Forecast horizon (days)")
    slider.set_value(30).run()

    assert not at.exception
    assert 30 in requested_days


def test_dashboard_events_filtered_by_type(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 100)
    client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "ADJUSTMENT",
            "quantity": -5,
            "event_id": "evt-adjustment-filter-test",
        },
    )
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    filter_select = next(s for s in at.selectbox if s.label == "Filter by event type")
    filter_select.select("ADJUSTMENT").run()

    assert not at.exception
    df = at.dataframe[0].value
    assert list(df["Event Type"].unique()) == ["ADJUSTMENT"]


def test_dashboard_events_pagination(client, dashboard_db, monkeypatch):
    product = create_product(client)
    for _ in range(25):
        purchase(client, product["id"], 1)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file("dashboard/app.py")
    _signed_in(at, user)
    at.run()

    assert not at.exception
    assert any("Page 1 of 2 (25 events)" in c.value for c in at.caption)
    assert len(at.dataframe[0].value) == 20

    next_button = next(b for b in at.button if b.label == "Next ➡")
    next_button.click().run()

    assert not at.exception
    assert any("Page 2 of 2 (25 events)" in c.value for c in at.caption)
    assert len(at.dataframe[0].value) == 5

    prev_button = next(b for b in at.button if b.label == "⬅ Previous")
    prev_button.click().run()

    assert not at.exception
    assert any("Page 1 of 2 (25 events)" in c.value for c in at.caption)


# ---------------------------------------------------------------------------
# Fleet Overview page (issue #71): portfolio-wide KPIs, urgency filtering,
# row-click deep link into Product Detail. AppTest has no way to simulate
# clicking a st.dataframe row (Dataframe testing element only exposes
# .value, no selection API), so the row-click -> st.switch_page() half of
# the deep link is verified live in the browser instead; these tests cover
# what AppTest can exercise: rendering, KPIs, filtering, and the *receiving*
# side of the deep link (product_detail.py pre-selecting from session_state).
# ---------------------------------------------------------------------------


def test_fleet_overview_renders_without_exception(client, dashboard_db, monkeypatch):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file(FLEET_OVERVIEW_PAGE)
    _signed_in(at, user)
    at.run()

    assert not at.exception


def test_fleet_overview_shows_portfolio_kpis(client, dashboard_db, monkeypatch):
    create_product(client, "Alpha")
    create_product(client, "Beta")
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file(FLEET_OVERVIEW_PAGE)
    _signed_in(at, user)
    at.run()

    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert metric_labels == ["Total Products", "Total Inventory", "Stockouts", "Needs Attention"]

    total_products = next(m for m in at.metric if m.label == "Total Products")
    assert total_products.value == "2"

    stockouts = next(m for m in at.metric if m.label == "Stockouts")
    assert stockouts.value == "2"  # neither product has any inventory yet


def test_fleet_overview_view_button_stages_deep_link(client, dashboard_db, monkeypatch):
    product = create_product(client, "Widget")
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file(FLEET_OVERVIEW_PAGE)
    _signed_in(at, user)
    at.run()

    view_button = next(b for b in at.button if b.label == "View →")
    view_button.click().run()

    assert at.session_state["deep_link_product_id"] == product["id"]


def test_fleet_overview_urgency_filter_narrows_table(client, dashboard_db, monkeypatch):
    stocked_out = create_product(client, "Stocked Out Item")
    healthy = create_product(client, "Healthy Item")
    purchase(client, healthy["id"], 1000)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file(FLEET_OVERVIEW_PAGE)
    _signed_in(at, user)
    at.run()

    filter_select = next(s for s in at.selectbox if s.label == "Filter by urgency")
    filter_select.select("STOCKOUT").run()

    assert not at.exception
    markdown_values = " ".join(m.value for m in at.markdown)
    assert f"Stocked Out Item ({stocked_out['sku']})" in markdown_values
    assert f"Healthy Item ({healthy['sku']})" not in markdown_values
    assert len([b for b in at.button if b.label == "View →"]) == 1


def test_product_detail_deep_link_preselects_product(client, dashboard_db, monkeypatch):
    product_a = create_product(client, "Alpha")
    product_b = create_product(client, "Beta")
    purchase(client, product_a["id"], 10)
    purchase(client, product_b["id"], 10)
    user = _make_dashboard_user(dashboard_db)

    _mock_forecast(monkeypatch)

    st.cache_data.clear()
    at = AppTest.from_file("dashboard/views/product_detail.py")
    _signed_in(at, user)
    at.session_state["deep_link_product_id"] = product_b["id"]
    at.run()

    assert not at.exception
    select = next(s for s in at.selectbox if s.label == "Select Product")
    assert select.value == product_b["id"]
    assert "deep_link_product_id" not in at.session_state
