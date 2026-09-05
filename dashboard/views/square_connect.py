# dashboard/views/square_connect.py
#
# Connect/disconnect Square POS (ROADMAP.md's "Food Cost Visibility"
# Phase 3). Admin-only, same reasoning as the Admin/Ops section on
# product_detail.py -- this changes an org-wide integration setting, not
# a per-product view. Routed via st.navigation()/st.Page() in
# dashboard/app.py — page_config and the auth gate happen once there,
# not per-page; require_login() here is a cheap no-op safety net for
# running this file standalone (dev, tests), not the real gate.
#
# The actual OAuth handshake happens outside this page entirely: this
# renders a link to Square's own hosted login, the user's browser
# navigates away and comes back once app/api/square.py's callback route
# finishes, at which point this page just reflects whatever connection
# state landed in the database.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard.auth import require_login
from dashboard.square_actions import disconnect, get_connect_url, get_connection_status

current_user = require_login()

st.title("🟩 Square POS Connector")

if current_user["role"] != "admin":
    st.info("Connecting a POS integration is an admin-only setting.")
    st.stop()

st.caption(
    "Connects IMS to your Square account (read-only) so sales data can flow "
    "in automatically instead of manual entry. You'll log into Square's own "
    "page — IMS never sees your Square password."
)

status = get_connection_status(current_user["organization_id"])

if status["connected"]:
    st.success(f"Connected to Square (merchant `{status['merchant_id']}`).")
    if status["needs_refresh"]:
        st.warning(
            "This connection's token is close to expiring and hasn't been "
            "renewed automatically yet — the sync job handles this once it "
            "exists (see ROADMAP.md's Phase 3)."
        )
    confirm_disconnect = st.checkbox("I understand this stops any Square sales sync")
    if st.button("Disconnect Square", disabled=not confirm_disconnect):
        disconnect(current_user["organization_id"])
        st.rerun()
else:
    st.info("Not connected to Square yet.")
    connect_url = get_connect_url(current_user["organization_id"])
    st.link_button("Connect to Square", connect_url)
