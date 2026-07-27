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

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard.admin_actions import run_export, run_replay
from dashboard.auth import require_login
from dashboard.data import load_events, load_forecast, load_inventory, load_products, load_restock

current_user = require_login()

st.title("🏭 Inventory Management Dashboard")
st.sidebar.header("Controls")

products = load_products()
if not products:
    st.info("No products yet — create some via the API first.")
    st.stop()

product_labels = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}

selected_product = st.sidebar.selectbox(
    "Select Product",
    options=list(product_labels.keys()),
    format_func=lambda pid: product_labels[pid],
)

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# ---------------------------------------------------------------
# Section 1 — Inventory metrics
# ---------------------------------------------------------------
current_qty = load_inventory(selected_product)
restock = load_restock(selected_product)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Current Inventory", f"{current_qty} units")

with col2:
    st.metric("Projected Demand (7d)", f"{restock['projected_demand_7d']} units")

with col3:
    st.metric("Recommended Order", f"{restock['recommended_order_qty']} units")

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
st.subheader("7-Day Demand Forecast")

try:
    with st.spinner("Loading forecast..."):
        forecast_df = load_forecast(selected_product)

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
# Section 4 — Event history table
# ---------------------------------------------------------------
st.divider()
st.subheader("Recent Inventory Events")

events = load_events(selected_product)

if events:
    st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
else:
    st.info("No events recorded for this product yet.")

# ---------------------------------------------------------------
# Section 5 — Admin / Ops (issue #72) — replay + export controls,
# previously only reachable via API or CLI. Gated on role, not just
# being logged in — Caddy basic_auth (see Caddyfile) is a
# network-perimeter control and doesn't distinguish members from
# admins, so this app-level check is what actually restricts it.
# ---------------------------------------------------------------
if current_user["role"] == "admin":
    st.divider()
    st.subheader("🔧 Admin / Ops")

    col_replay, col_export = st.columns(2)

    with col_replay:
        st.caption(
            "Rebuilds the inventory_state projection from scratch by replaying every "
            "inventory event. Safe to run — it only recomputes derived state, never "
            "touches the event log itself — but affects every product, not just the "
            "one selected above."
        )
        confirm_replay = st.checkbox("I understand this rebuilds inventory state for all products")
        if st.button("Rebuild inventory projection", disabled=not confirm_replay):
            with st.spinner("Replaying events..."):
                summary = run_replay(current_user["id"])
            st.cache_data.clear()
            st.success(
                f"Rebuilt state for {summary['products_rebuilt']} products from "
                f"{summary['events_processed']} events."
            )

    with col_export:
        st.caption(
            "Exports inventory events to the data lake (Parquet), incrementally — "
            "only events since the last export checkpoint."
        )
        if st.button("Export inventory events"):
            with st.spinner("Exporting..."):
                result = run_export(current_user["id"])
            if result["rows_exported"] == 0:
                st.info("Nothing new to export since the last checkpoint.")
            else:
                st.success(
                    f"Exported {result['rows_exported']} rows across "
                    f"{result['files_written']} file(s)."
                )
