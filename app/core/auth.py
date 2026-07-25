import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

_API_KEY = os.getenv("API_KEY")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# Falls back to a fixed dev-only value so login works out of the box
# locally, same convenience as API_KEY/WEBHOOK_SECRET being unset — but
# unlike those, there's no way to "disable" JWT signing, so an operator
# who forgets to set this in production gets a predictable secret rather
# than a broken endpoint. Must be set for real deployments (see
# .env.example and SECURITY.md).
_JWT_SECRET = os.getenv("JWT_SECRET") or "insecure-dev-secret-do-not-use-in-production"
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY = timedelta(hours=12)

_bearer_scheme = HTTPBearer(auto_error=False)


def require_api_key(key: str = Security(_api_key_header)) -> None:
    """
    Checks X-API-Key header against the API_KEY env var.
    Auth is disabled when API_KEY is not set (local dev).
    """
    if _API_KEY is None:
        return
    if key is None or not hmac.compare_digest(key, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_webhook_signature(request: Request) -> None:
    """
    Verifies the X-Webhook-Signature header against an HMAC-SHA256 digest
    of the raw request body, keyed by the WEBHOOK_SECRET env var — same
    constant-time-comparison idiom as require_api_key, applied to a
    computed digest instead of a shared string. Signature check is a no-op
    when WEBHOOK_SECRET is unset (local dev), same as API_KEY.

    Reads the raw body via request.body() before the route handler parses
    it as JSON — Starlette caches the body after the first read, so the
    route's Pydantic body model still parses correctly afterward.
    """
    if _WEBHOOK_SECRET is None:
        return

    signature = request.headers.get("X-Webhook-Signature")
    body = await request.body()
    expected = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    if signature is None or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook signature")


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + _JWT_EXPIRY,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decodes and validates a JWT bearer token, then loads the corresponding
    User row. Rejects deactivated users even with an otherwise-valid,
    unexpired token — is_active is checked on every request, not just at
    login, so deactivating an account takes effect immediately.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    try:
        payload = jwt.decode(credentials.credentials, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    return user
