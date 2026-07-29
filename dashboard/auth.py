# dashboard/auth.py
#
# Gates the dashboard on a real user account. No HTTP call, no bearer
# token — the dashboard already calls service-layer functions directly
# against app.database.SessionLocal (see dashboard/data.py), so this
# reuses authenticate_user() the same in-process way. Coexists with
# Caddy's basic_auth (see Caddyfile) rather than replacing it — that's a
# network-perimeter control, this is per-user attribution inside the app.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.exceptions import InvalidCredentialsError
from app.database import SessionLocal
from app.services.auth_service import authenticate_user


def login_form() -> None:
    st.title("🏭 IMS Dashboard")
    st.subheader("Sign in")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if not submitted:
        return

    db = SessionLocal()
    try:
        user = authenticate_user(db, email, password)
    except InvalidCredentialsError:
        st.error("Invalid email or password")
        return
    finally:
        db.close()

    # id/email/display_name/role/organization_id only — never a password or
    # token. There's no token to hold: this session lives entirely
    # server-side in Streamlit's own session state, not in anything sent
    # back to the browser. role was included so a future admin-only page
    # (issue #72) could gate on st.session_state["user"]["role"] without
    # touching this file again — organization_id is here for the same
    # reason, so later Epoch 10 PRs' dashboard call sites can read it
    # without another change here.
    st.session_state["user"] = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "organization_id": user.organization_id,
    }
    st.rerun()


def require_login() -> dict:
    """
    Call at the very top of dashboard/app.py, right after
    st.set_page_config() (which must itself be the first Streamlit call
    in the script). st.stop() halts the rest of the script for this run,
    so nothing below it — metrics, charts, event tables — executes for an
    unauthenticated visitor.
    """
    if "user" not in st.session_state:
        login_form()
        st.stop()

    return st.session_state["user"]
