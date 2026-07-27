# dashboard/views/fleet_overview.py
#
# Portfolio-wide view across every product (issue #71) — built on top of
# get_fleet_status() (issue #68). Routed via st.navigation()/st.Page() in
# dashboard/app.py — page_config and the auth gate happen once there,
# not per-page; require_login() here is a cheap no-op safety net for
# running this file standalone (dev, tests), not the real gate.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard.auth import require_login
from dashboard.data import load_fleet_status

require_login()

st.title("🚦 Fleet Overview")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

fleet = load_fleet_status()

if not fleet:
    st.info("No products yet — create some via the API first.")
    st.stop()

# ---------------------------------------------------------------
# Section 1 — Portfolio-wide KPIs
# ---------------------------------------------------------------
urgency_counts = {"STOCKOUT": 0, "URGENT": 0, "LOW": 0, "OK": 0, "NO_FORECAST": 0}
for p in fleet:
    urgency_counts[p["urgency"]] += 1

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Products", len(fleet))
with col2:
    st.metric("Total Inventory", f"{sum(p['current_inventory'] for p in fleet)} units")
with col3:
    st.metric("Stockouts", urgency_counts["STOCKOUT"])
with col4:
    st.metric("Needs Attention", urgency_counts["URGENT"] + urgency_counts["LOW"])

# ---------------------------------------------------------------
# Section 2 — Urgency filter + fleet table
# ---------------------------------------------------------------
st.divider()

urgency_filter = st.selectbox(
    "Filter by urgency", options=["All", "STOCKOUT", "URGENT", "LOW", "OK", "NO_FORECAST"]
)

filtered_fleet = (
    fleet if urgency_filter == "All" else [p for p in fleet if p["urgency"] == urgency_filter]
)

if not filtered_fleet:
    st.info("No products match this urgency filter.")
    st.stop()

# A plain st.dataframe with on_select="rerun"/selection_mode="single-row"
# would be the more obvious way to build a clickable table, but it
# reproducibly segfaults the Streamlit server the moment a real browser
# interacts with the rendered grid in this environment (confirmed against
# two independent Streamlit processes, isolated from any specific data —
# a bare 3-row dataframe reproduces it too). Row-level st.button()s avoid
# that widget entirely and match the pattern already used elsewhere in
# this dashboard (e.g. Purchase Orders' per-PO action buttons).
urgency_icons = {"STOCKOUT": "🔴", "URGENT": "🟠", "LOW": "🟡", "OK": "🟢", "NO_FORECAST": "⚪"}

st.caption("Click View to open that product's detail page.")
column_widths = [3, 1.5, 1.5, 2, 2, 1.2]
header_cols = st.columns(column_widths)
for col, label in zip(
    header_cols, ["Product", "Inventory", "Urgency", "Recommended Order", "Days of Stock", ""]
):
    col.markdown(f"**{label}**")

for p in filtered_fleet:
    row_cols = st.columns(column_widths)
    row_cols[0].write(f"{p['name']} ({p['sku']})")
    row_cols[1].write(p["current_inventory"])
    row_cols[2].write(f"{urgency_icons.get(p['urgency'], '')} {p['urgency']}")
    row_cols[3].write(p["recommended_order_qty"])
    row_cols[4].write(p["days_of_stock_remaining"])
    if row_cols[5].button("View →", key=f"view_{p['product_id']}"):
        st.session_state["deep_link_product_id"] = p["product_id"]
        st.switch_page("views/product_detail.py")
