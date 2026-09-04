# dashboard/views/waste_entry.py
#
# Quick waste logging — the single biggest gap surfaced by
# docs/product/food-cost-visibility-discovery.md: waste is currently
# tracked nowhere in this app, at an estimated 8-15 small events per
# shift. Deliberately minimal by design, not an oversight — the
# discovery's own finding was that anything requiring more than a
# product pick + a rough quantity doesn't survive a kitchen rush
# ("nobody's gonna walk over to a clipboard... by day four the pen's
# missing"). No free-text field, no event-type picker (hardcoded to
# WASTE — see ROADMAP.md's "Food Cost Visibility" Phase 1 for why a
# broader picker is explicitly out of scope here), no multi-step flow.
#
# Routed via st.navigation()/st.Page() in dashboard/app.py — page_config
# and the auth gate happen once there, not per-page; require_login() here
# is a cheap no-op safety net for running this file standalone (dev,
# tests), not the real gate.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.exceptions import DomainError
from dashboard.auth import require_login
from dashboard.data import invalidate_fleet_status, invalidate_product_views, load_products
from dashboard.waste_actions import log_waste

current_user = require_login()

st.title("🗑️ Log Waste")
st.caption("Spoiled or thrown-out stock — pick the product, enter roughly how much, done.")

products = load_products(current_user["organization_id"])
if not products:
    st.info("No products yet — create some via the API first.")
    st.stop()

product_labels = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}

with st.form("log_waste_form", clear_on_submit=True):
    product_id = st.selectbox(
        "Product", options=list(product_labels.keys()), format_func=lambda pid: product_labels[pid]
    )
    quantity = st.number_input("Quantity", min_value=1, value=1)
    submitted = st.form_submit_button("Log waste", use_container_width=True)

if submitted:
    try:
        log_waste(
            int(product_id), int(quantity), current_user["id"], current_user["organization_id"]
        )
    except DomainError as e:
        st.error(str(e))
    else:
        invalidate_product_views(int(product_id), current_user["organization_id"])
        invalidate_fleet_status(current_user["organization_id"])
        st.success(f"Logged {int(quantity)} × {product_labels[product_id]} as waste.")
