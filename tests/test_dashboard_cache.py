# tests/test_dashboard_cache.py
#
# Coverage for dashboard/data.py's invalidate_* helpers, which replaced a
# bare st.cache_data.clear() at every dashboard mutation call site (issue
# #283) -- a bare clear() flushes every org's cached entries, not just the
# one that actually changed. Proves the targeted helpers actually scope
# invalidation to one org, leaving another org's cached entry untouched.
#
# Loaders work fine called directly outside a Streamlit script context
# (confirmed empirically -- just a harmless "no ScriptRunContext"
# warning), so no AppTest is needed for this unit-level coverage.
#
# dashboard.data is imported lazily inside each test body, not at module
# level -- dashboard.data does `from app.database import SessionLocal` at
# its own import time, binding an independent name that only resolves to
# the test engine if the import happens after the `dashboard_db` fixture's
# monkeypatch has already run (same "independent name" issue documented
# in conftest.py's set_user_role_db/admin_actions_db fixtures).

import pytest
import streamlit as st

from app.models.product import Product


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """
    st.cache_data's cache is process-wide, not reset per test -- unlike
    every DB fixture here, which gets a fresh DB per test. Without this,
    a cache entry for organization_id=1 populated by an earlier test
    (against that test's own now-torn-down DB) leaks into this file's
    exact-count assertions. This file is the first to assert on cached
    return values precisely enough to expose that pre-existing gap; a
    real deployment doesn't hit it since org 1 there is one long-lived
    DB, not a fresh one per request.
    """
    st.cache_data.clear()
    yield


def _make_product(dashboard_db, name, sku, organization_id):
    session = dashboard_db()
    try:
        product = Product(name=name, sku=sku, organization_id=organization_id)
        session.add(product)
        session.commit()
        session.refresh(product)
        return product
    finally:
        session.close()


def test_invalidate_products_does_not_evict_other_orgs_cache(dashboard_db, second_org):
    from dashboard.data import invalidate_products, load_products

    _make_product(dashboard_db, "Org1 Widget", "org1-widget", 1)
    _make_product(dashboard_db, "Org2 Widget", "org2-widget", second_org.id)

    org1_first = load_products(1)
    org2_first = load_products(second_org.id)
    assert len(org1_first) == 1
    assert len(org2_first) == 1

    # A 2nd org-1 product, written directly at the DB layer -- load_products
    # is cached, so a fresh call must still return the stale (1-item)
    # result until explicitly invalidated.
    _make_product(dashboard_db, "Org1 Widget 2", "org1-widget-2", 1)

    stale_org1 = load_products(1)
    assert len(stale_org1) == 1

    invalidate_products(1)

    fresh_org1 = load_products(1)
    assert len(fresh_org1) == 2

    # Org 2's cache entry was never touched by org 1's invalidation --
    # the whole point of a per-org helper instead of a bare clear().
    still_cached_org2 = load_products(second_org.id)
    assert len(still_cached_org2) == 1


def test_invalidate_inventory_does_not_evict_other_orgs_cache(dashboard_db, second_org):
    from dashboard.data import invalidate_inventory, load_inventory

    org1_product = _make_product(dashboard_db, "Org1 Widget", "org1-widget", 1)
    org2_product = _make_product(dashboard_db, "Org2 Widget", "org2-widget", second_org.id)

    assert load_inventory(org1_product.id, 1) == 0
    assert load_inventory(org2_product.id, second_org.id) == 0

    session = dashboard_db()
    try:
        from app.models.inventory_state import InventoryState

        state = InventoryState(product_id=org1_product.id, organization_id=1, quantity=50)
        session.add(state)
        session.commit()
    finally:
        session.close()

    # Still stale/cached until invalidated.
    assert load_inventory(org1_product.id, 1) == 0

    invalidate_inventory(org1_product.id, 1)

    assert load_inventory(org1_product.id, 1) == 50
    # Org 2's product-level cache entry is untouched.
    assert load_inventory(org2_product.id, second_org.id) == 0


def test_invalidate_purchase_orders_clears_every_status_filter_variant(dashboard_db, second_org):
    """
    load_purchase_orders is keyed on (status, organization_id) -- a
    viewer could have any of the 4 status-filter values cached
    (None/DRAFT/SUBMITTED/RECEIVED) depending on what they'd selected.
    invalidate_purchase_orders(org_id) must clear all 4 for that org
    without touching another org's entries.
    """
    from dashboard.data import invalidate_purchase_orders, load_purchase_orders

    # Populate every status-filter cache entry for both orgs.
    for status in (None, "DRAFT", "SUBMITTED", "RECEIVED"):
        assert load_purchase_orders(status, 1) == []
        assert load_purchase_orders(status, second_org.id) == []

    session = dashboard_db()
    try:
        from app.core.security import hash_password
        from app.models.enums import PurchaseOrderStatus
        from app.models.purchase_order import PurchaseOrder
        from app.models.supplier import Supplier
        from app.models.user import User

        supplier = Supplier(name="Test Supplier", organization_id=1)
        user = User(
            email="po-cache-test@example.com",
            password_hash=hash_password("pw"),
            display_name="PO Cache Test",
            organization_id=1,
        )
        session.add_all([supplier, user])
        session.commit()

        session.add(
            PurchaseOrder(
                supplier_id=supplier.id,
                status=PurchaseOrderStatus.DRAFT,
                organization_id=1,
                created_by_id=user.id,
            )
        )
        session.commit()
    finally:
        session.close()

    # Every status-filter variant for org 1 is still stale until invalidated.
    for status in (None, "DRAFT", "SUBMITTED", "RECEIVED"):
        assert load_purchase_orders(status, 1) == []

    invalidate_purchase_orders(1)

    assert len(load_purchase_orders(None, 1)) == 1
    assert len(load_purchase_orders("DRAFT", 1)) == 1
    assert load_purchase_orders("SUBMITTED", 1) == []

    # Org 2's entries were never touched.
    for status in (None, "DRAFT", "SUBMITTED", "RECEIVED"):
        assert load_purchase_orders(status, second_org.id) == []
