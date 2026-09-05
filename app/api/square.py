# app/api/square.py
#
# Only the OAuth callback lives here as a real HTTP endpoint -- Square (an
# external server) calls this directly, so it can't go through the
# in-process dashboard-action pattern the rest of this app uses
# (dashboard/square_actions.py, once it exists, calls
# square_service.get_authorize_url() directly to build the "Connect to
# Square" link). This route is deliberately public/unauthenticated
# (registered without the app-wide _auth dependency, same as
# webhooks_router) -- Square's own redirect carries no IMS bearer token,
# only the signed `state` parameter, which is this route's actual auth
# check.

import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database import get_db
from app.services import square_service

router = APIRouter(prefix="/square", tags=["square"])

# Must exactly match the redirect_uri used to build the authorize URL in
# the first place -- Square rejects a mismatch. Kept as its own env var
# (not reusing CORS_ORIGINS, which is about *browser* origins, not this
# server-to-server callback URL) so it can point at this API's real
# public address in any deployment.
_SQUARE_REDIRECT_URI = os.getenv("SQUARE_REDIRECT_URI", "http://localhost:8000/api/square/callback")

# Where to bounce the seller's browser back to once the connect flow
# finishes, success or failure -- the dashboard, not this API. First
# CORS_ORIGINS entry is already exactly that address in every existing
# deployment shape (self-hosted, desktop, mobile-over-Tailscale).
_DASHBOARD_URL = os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")[0]


def square_redirect_uri() -> str:
    return _SQUARE_REDIRECT_URI


@router.get("/callback")
def square_oauth_callback(
    code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)
):
    try:
        organization_id = square_service.verify_state(state)
        token_response = square_service.exchange_code_for_token(code, _SQUARE_REDIRECT_URI)
        square_service.save_connection(db, organization_id, token_response)
    except square_service.SquareOAuthError as e:
        logger.warning("square_oauth_callback_failed", extra={"error": str(e)})
        return RedirectResponse(url=f"{_DASHBOARD_URL}?square_error={e}")

    return RedirectResponse(url=f"{_DASHBOARD_URL}?square_connected=true")
