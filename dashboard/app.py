# dashboard/app.py
#
# Entry point / router (issue #69). Streamlit re-executes this file on
# every rerun, then hands off to whichever page under dashboard/views/
# is selected — see st.navigation()'s docstring. page_config and the
# auth gate live here, once, rather than being duplicated per page.

import sys
from pathlib import Path

import streamlit as st

# Add project root to path so app imports resolve correctly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.auth import require_login

# ---------------------------------------------------------------
# Page config — must be the first Streamlit call in the script
# ---------------------------------------------------------------
st.set_page_config(page_title="IMS Dashboard", page_icon="🏭", layout="wide")

# ---------------------------------------------------------------
# Auth gate — blocks everything below for an unauthenticated visitor.
# Coexists with Caddy basic_auth in the self-hosted deploy (see
# Caddyfile); that's a network-perimeter control, this is per-user
# attribution inside the app.
# ---------------------------------------------------------------
current_user = require_login()

st.sidebar.caption(f"Signed in as {current_user['display_name']}")
if st.sidebar.button("Sign out"):
    del st.session_state["user"]
    st.rerun()

pages = [
    st.Page("views/product_detail.py", title="Product Detail", icon="📊", default=True),
    st.Page("views/fleet_overview.py", title="Fleet Overview", icon="🚦"),
    st.Page("views/recipes.py", title="Recipes / BOM", icon="🍳"),
    st.Page("views/purchase_orders.py", title="Purchase Orders", icon="📦"),
]

pg = st.navigation(pages)
pg.run()
