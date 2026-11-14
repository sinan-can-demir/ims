# dashboard/auth.py
#
# Gates the dashboard on a real user account. No HTTP call, no bearer
# token — the dashboard already calls service-layer functions directly
# against app.database.SessionLocal (see dashboard/data.py), so this
# reuses authenticate_user() the same in-process way. Coexists with
# Caddy's basic_auth (see deploy/Caddyfile) rather than replacing it — that's a
# network-perimeter control, this is per-user attribution inside the app.

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.exceptions import InvalidCredentialsError
from app.database import SessionLocal
from app.models.user import User
from app.services.auth_service import authenticate_user

# Key (not a user-facing string) set after a forced logout so the login form
# can tell the person why they're looking at it. Set AFTER session_state is
# cleared, and popped by login_form() so it only shows once.
_SESSION_ENDED_KEY = "_session_ended_notice"


def _session_user(user: User) -> dict:
    """
    The one shape stored in st.session_state["user"] — used by login and by
    the per-run refresh in require_login(), so the two can never drift apart
    (pages read role/organization_id from this dict).
    """
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "organization_id": user.organization_id,
    }


def login_form() -> None:
    st.title("🏭 IMS Dashboard")
    st.subheader("Sign in")

    if st.session_state.pop(_SESSION_ENDED_KEY, False):
        st.warning("Your session has ended. Please sign in again.")

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
    st.session_state["user"] = _session_user(user)
    st.rerun()


def require_login() -> dict:
    """
    Call at the very top of dashboard/app.py, right after
    st.set_page_config() (which must itself be the first Streamlit call
    in the script). st.stop() halts the rest of the script for this run,
    so nothing below it — metrics, charts, event tables — executes for an
    unauthenticated visitor.

    Re-reads the user row from the DB on EVERY script run (#388), the same
    way the API's require_current_user does on every request. The session
    holds only a snapshot taken at login, so without this a deactivated
    user, or an admin demoted via scripts/set_user_role.py, would keep their
    old role and data access until their browser session ended. A missing or
    inactive user is signed out exactly like the Sign out button
    (st.session_state.clear()) and shown the login form with a notice. The
    role/org in the returned dict are refreshed from the DB. Deliberately
    uncached (a cache would reintroduce the stale window) and lockout is not
    rechecked, matching the API.
    """
    if "user" not in st.session_state:
        login_form()
        st.stop()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == st.session_state["user"]["id"]).first()
        fresh = _session_user(user) if user is not None and user.is_active else None
    finally:
        db.close()

    if fresh is None:
        st.session_state.clear()
        st.session_state[_SESSION_ENDED_KEY] = True
        login_form()
        st.stop()

    st.session_state["user"] = fresh
    return fresh
