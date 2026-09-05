# app/services/square_service.py
#
# Square POS connector (ROADMAP.md's "Food Cost Visibility" Phase 3).
# OAuth authorization-code flow -- the seller logs into Square's own
# hosted page and never hands IMS a credential directly, matching the
# discovery's "bank-app-style login" requirement (see
# docs/product/food-cost-visibility-discovery.md).
#
# Tokens are stored in plaintext on Organization (see that model's
# comment) -- same posture as webhook_secret, a known limitation to
# revisit before any real deployment, not silently swept under the rug.

import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.models.organization import Organization

SQUARE_APPLICATION_ID = os.getenv("SQUARE_APPLICATION_ID")
SQUARE_APPLICATION_SECRET = os.getenv("SQUARE_APPLICATION_SECRET")
SQUARE_API_BASE_URL = os.getenv("SQUARE_API_BASE_URL", "https://connect.squareupsandbox.com")

# Least-privilege, matching OAuth best practice -- this connector only
# ever reads sales data, never writes anything back to Square.
_OAUTH_SCOPE = "ORDERS_READ MERCHANT_PROFILE_READ"

# Same fallback string as app/core/auth.py's _JWT_SECRET -- read
# independently here rather than importing that module's private name
# across a service boundary. Used only to sign the OAuth `state`
# parameter (CSRF protection), not to sign real JWTs.
_STATE_SECRET = os.getenv("JWT_SECRET") or "insecure-dev-secret-do-not-use-in-production"

# 10 minutes -- long enough for a real login, short enough to bound replay.
_STATE_MAX_AGE_SECONDS = 600


class SquareOAuthError(DomainError):
    pass


def _sign_state(organization_id: int, timestamp: int) -> str:
    payload = f"{organization_id}:{timestamp}"
    signature = hmac.new(
        _STATE_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{signature}"


def make_state(organization_id: int) -> str:
    """
    A signed, timestamped state parameter -- Square echoes this back
    unmodified in the callback, so it doubles as CSRF protection (a
    forged callback can't produce a valid signature without
    _STATE_SECRET) and as how the callback recovers which org initiated
    the connect flow (Square's own callback carries no organization_id of
    its own).
    """
    return _sign_state(organization_id, int(time.time()))


def verify_state(state: str) -> int:
    """Returns the org id embedded in a valid, unexpired state, else raises SquareOAuthError."""
    parts = state.split(":")
    if len(parts) != 3:
        raise SquareOAuthError("Invalid Square OAuth state parameter.")

    organization_id_str, timestamp_str, signature = parts
    try:
        organization_id = int(organization_id_str)
        timestamp = int(timestamp_str)
    except ValueError as e:
        raise SquareOAuthError("Invalid Square OAuth state parameter.") from e

    expected = _sign_state(organization_id, timestamp)
    # Constant-time compare -- this is a security-relevant signature
    # check, same reasoning as the webhook HMAC verification.
    if not hmac.compare_digest(expected, state):
        raise SquareOAuthError("Square OAuth state signature does not match.")

    if time.time() - timestamp > _STATE_MAX_AGE_SECONDS:
        raise SquareOAuthError("Square OAuth state has expired -- please reconnect.")

    return organization_id


def get_authorize_url(organization_id: int, redirect_uri: str) -> str:
    if not SQUARE_APPLICATION_ID:
        raise SquareOAuthError("SQUARE_APPLICATION_ID is not configured.")

    state = make_state(organization_id)
    return (
        f"{SQUARE_API_BASE_URL}/oauth2/authorize"
        f"?client_id={SQUARE_APPLICATION_ID}"
        f"&scope={_OAUTH_SCOPE.replace(' ', '+')}"
        f"&session=false"
        f"&state={state}"
        f"&redirect_uri={redirect_uri}"
    )


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    if not SQUARE_APPLICATION_ID or not SQUARE_APPLICATION_SECRET:
        raise SquareOAuthError(
            "SQUARE_APPLICATION_ID/SQUARE_APPLICATION_SECRET are not configured."
        )

    response = httpx.post(
        f"{SQUARE_API_BASE_URL}/oauth2/token",
        json={
            "client_id": SQUARE_APPLICATION_ID,
            "client_secret": SQUARE_APPLICATION_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        raise SquareOAuthError(f"Square token exchange failed: {response.text}")

    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    if not SQUARE_APPLICATION_ID or not SQUARE_APPLICATION_SECRET:
        raise SquareOAuthError(
            "SQUARE_APPLICATION_ID/SQUARE_APPLICATION_SECRET are not configured."
        )

    response = httpx.post(
        f"{SQUARE_API_BASE_URL}/oauth2/token",
        json={
            "client_id": SQUARE_APPLICATION_ID,
            "client_secret": SQUARE_APPLICATION_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        raise SquareOAuthError(f"Square token refresh failed: {response.text}")

    return response.json()


def save_connection(db: Session, organization_id: int, token_response: dict) -> Organization:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise SquareOAuthError(f"Organization {organization_id} not found.")

    org.square_access_token = token_response["access_token"]
    org.square_refresh_token = token_response.get("refresh_token")
    org.square_merchant_id = token_response.get("merchant_id")
    # Square returns expires_at as an RFC 3339 string already.
    org.square_token_expires_at = datetime.fromisoformat(token_response["expires_at"])

    db.commit()
    db.refresh(org)
    return org


def disconnect(db: Session, organization_id: int) -> None:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise SquareOAuthError(f"Organization {organization_id} not found.")

    org.square_access_token = None
    org.square_refresh_token = None
    org.square_merchant_id = None
    org.square_token_expires_at = None
    db.commit()


def is_connected(org: Organization) -> bool:
    return org.square_access_token is not None


def needs_token_refresh(org: Organization, within: timedelta = timedelta(days=7)) -> bool:
    """
    Square recommends renewing every <=7 days rather than waiting near
    the real 30-day expiry, to leave time to discover/resolve a failed
    refresh before the token actually stops working.
    """
    if org.square_token_expires_at is None:
        return False
    return datetime.now(timezone.utc) >= org.square_token_expires_at - within
