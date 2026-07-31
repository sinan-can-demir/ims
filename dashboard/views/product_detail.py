# dashboard/views/product_detail.py
#
# Per-product overview: current inventory, restock urgency, demand
# forecast, and recent event history — plus the admin/ops panel (issue
# #72), gated on role. Routed via st.navigation()/st.Page() in
# dashboard/app.py — page_config and the auth gate happen once there,
# not per-page; require_login() here is a cheap no-op safety net for
# running this file standalone (dev, tests), not the real gate.
#
# Product selector is DB-sourced (load_products(), issue #69) instead of
# reading feature_store/daily_sales.parquet directly — a product with no
# sales history yet never had a parquet row, so it was previously
# invisible here even though it exists.

import math
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.models.enums import EventType
from dashboard.admin_actions import run_replay
from dashboard.auth import require_login
from dashboard.data import load_events, load_forecast, load_inventory, load_products, load_restock

EVENTS_PAGE_SIZE = 20
PRODUCT_SELECT_KEY = "product_detail_selected_product"

current_user = require_login()

st.title("🏭 Inventory Management Dashboard")
st.sidebar.header("Controls")

products = load_products(current_user["organization_id"])
if not products:
    st.info("No products yet — create some via the API first.")
    st.stop()

product_labels = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}

# A row-click deep link from Fleet Overview (issue #71) stashes the target
# product id here before switching pages. Assigning to the widget's own
# session_state key *before* the widget is created is what makes the
# selectbox actually open on that product instead of its default.
if "deep_link_product_id" in st.session_state:
    st.session_state[PRODUCT_SELECT_KEY] = st.session_state.pop("deep_link_product_id")

selected_product = st.sidebar.selectbox(
    "Select Product",
    options=list(product_labels.keys()),
    format_func=lambda pid: product_labels[pid],
    key=PRODUCT_SELECT_KEY,
)

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# ---------------------------------------------------------------
# Section 1 — Inventory metrics
# ---------------------------------------------------------------
current_qty = load_inventory(selected_product, current_user["organization_id"])
restock = load_restock(selected_product, current_user["organization_id"])

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Current Inventory", f"{current_qty} units")

with col2:
    st.metric("Projected Demand (7d)", f"{restock['projected_demand_7d']} units")

with col3:
    st.metric("Recommended Order", f"{restock['recommended_order_qty']} units")

col4, col5 = st.columns(2)

with col4:
    st.metric("Safety Stock", f"{restock['safety_stock']} units")

with col5:
    st.metric("Days of Stock Remaining", f"{restock['days_of_stock_remaining']} days")

# ---------------------------------------------------------------
# Section 2 — Restock alert
# ---------------------------------------------------------------
urgency_config = {
    "STOCKOUT": ("🔴", "error"),
    "URGENT": ("🟠", "warning"),
    "LOW": ("🟡", "warning"),
    "OK": ("🟢", "success"),
}

icon, alert_type = urgency_config[restock["urgency"]]

if alert_type == "error":
    st.error(
        f"{icon} {restock['urgency']} — Restock immediately! "
        f"Order {restock['recommended_order_qty']} units."
    )
elif alert_type == "warning":
    st.warning(
        f"{icon} {restock['urgency']} — "
        f"{restock['days_of_stock_remaining']} days of stock remaining. "
        f"Order {restock['recommended_order_qty']} units."
    )
else:
    st.success(f"{icon} Stock levels are healthy.")

# ---------------------------------------------------------------
# Section 3 — Forecast chart
# ---------------------------------------------------------------
st.divider()
st.subheader("Demand Forecast")

forecast_days = st.slider(
    "Forecast horizon (days)",
    min_value=1,
    max_value=90,  # matches GET /api/forecast/{product_id}'s days bound
    value=7,
)

try:
    with st.spinner("Loading forecast..."):
        forecast_df = load_forecast(
            selected_product, current_user["organization_id"], forecast_days
        )

    fig = go.Figure()

    # Shaded confidence band
    fig.add_trace(
        go.Scatter(
            x=pd.concat([forecast_df["ds"], forecast_df["ds"][::-1]]),
            y=pd.concat([forecast_df["yhat_upper"], forecast_df["yhat_lower"][::-1]]),
            fill="toself",
            fillcolor="rgba(99, 102, 241, 0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            name="Confidence interval",
        )
    )

    # Predicted demand line
    fig.add_trace(
        go.Scatter(
            x=forecast_df["ds"],
            y=forecast_df["yhat"].clip(lower=0),
            mode="lines+markers",
            line=dict(color="#6366f1", width=2),
            marker=dict(size=6),
            name="Predicted demand",
        )
    )

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Units",
        hovermode="x unified",
        height=350,
        margin=dict(l=0, r=0, t=20, b=0),
    )

    st.plotly_chart(fig, use_container_width=True)

except FileNotFoundError:
    st.info("⚠️ No trained model found for this product. Run make train first.")

# ---------------------------------------------------------------
# Section 4 — Event history table (filter + pagination, issue #70)
# ---------------------------------------------------------------
st.divider()
st.subheader("Inventory Events")

event_type_filter = st.selectbox(
    "Filter by event type", options=["All", *(e.value for e in EventType)]
)

# Reset to page 1 whenever the product or filter changes — otherwise a
# stale page number from a longer list could point past the end of a
# shorter, newly-filtered one.
events_filter_key = (selected_product, event_type_filter)
if st.session_state.get("_events_filter_key") != events_filter_key:
    st.session_state["_events_filter_key"] = events_filter_key
    st.session_state["events_page"] = 1

page = st.session_state.setdefault("events_page", 1)
offset = (page - 1) * EVENTS_PAGE_SIZE
event_type_arg = None if event_type_filter == "All" else event_type_filter

events_result = load_events(
    selected_product, current_user["organization_id"], event_type_arg, EVENTS_PAGE_SIZE, offset
)
events = events_result["events"]
total_events = events_result["total"]

if events:
    st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
else:
    st.info("No events match this filter.")

total_pages = max(1, math.ceil(total_events / EVENTS_PAGE_SIZE))
col_prev, col_page, col_next = st.columns([1, 2, 1])
with col_prev:
    if st.button("⬅ Previous", disabled=page <= 1):
        st.session_state["events_page"] = page - 1
        st.rerun()
with col_page:
    st.caption(f"Page {page} of {total_pages} ({total_events} events)")
with col_next:
    if st.button("Next ➡", disabled=page >= total_pages):
        st.session_state["events_page"] = page + 1
        st.rerun()

# ---------------------------------------------------------------
# Section 5 — Admin / Ops (issue #72) — replay control, previously
# only reachable via API or CLI. Gated on role, not just being logged
# in — Caddy basic_auth (see Caddyfile) is a network-perimeter control
# and doesn't distinguish members from admins, so this app-level check
# is what actually restricts it.
#
# The export button that used to live here was removed in Epoch 10 PR
# 13 (#149) — the export checkpoint is a whole-deployment, cross-org
# operation, so a single org's admin triggering it from their own
# per-org dashboard was never the right shape once real multi-tenancy
# existed. It's an ops-only cron/CLI action now, see
# docs/deployment/self-hosted.md.
# ---------------------------------------------------------------
if current_user["role"] == "admin":
    st.divider()
    st.subheader("🔧 Admin / Ops")

    st.caption(
        "Rebuilds the inventory_state projection from scratch by replaying every "
        "inventory event. Safe to run — it only recomputes derived state, never "
        "touches the event log itself — but affects every product, not just the "
        "one selected above."
    )
    confirm_replay = st.checkbox("I understand this rebuilds inventory state for all products")
    if st.button("Rebuild inventory projection", disabled=not confirm_replay):
        with st.spinner("Replaying events..."):
            summary = run_replay(current_user["id"], current_user["organization_id"])
        st.cache_data.clear()
        st.success(
            f"Rebuilt state for {summary['products_rebuilt']} products from "
            f"{summary['events_processed']} events."
        )
