import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database import get_db
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User

# Falls back to a fixed dev-only value so login works out of the box
# locally, same convenience as WEBHOOK_SECRET being unset — but unlike
# that, there's no way to "disable" JWT signing, so an operator who
# forgets to set this in production gets a predictable secret rather
# than a broken endpoint. Must be set for real deployments (see
# .env.example and SECURITY.md).
_JWT_SECRET = os.getenv("JWT_SECRET") or "insecure-dev-secret-do-not-use-in-production"
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY = timedelta(hours=12)

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_webhook_signature(
    organization_id: int, request: Request, db: Session = Depends(get_db)
) -> None:
    """
    Verifies the X-Webhook-Signature header against an HMAC-SHA256 digest
    of the raw request body, keyed by the target org's own
    organizations.webhook_secret (Epoch 10 PR 12, #148) — no longer a
    single global WEBHOOK_SECRET env var, since a shared secret across
    every org would let any one org's webhook credential post events
    into any other org. organization_id here is resolved from the same
    path param as the route it's attached to (POST
    /webhooks/{organization_id}/ingest), not a query/body field — same
    constant-time-comparison idiom (hmac.compare_digest) used for the old
    API_KEY check, applied to a computed digest instead of a shared
    string.

    Fails closed (401) when the org's webhook_secret is NULL. Every org
    is provisioned with a real random secret at creation time now (see
    scripts/create_organization.py), so a NULL here means a genuinely
    misconfigured org, not "signature verification intentionally
    disabled" — that state used to silently accept unsigned requests,
    which is exactly the shape of an unauthenticated ingest endpoint on
    every org in every deployment, since the only real provisioning
    path never set the secret. Uses the same 401 detail as an
    actually-wrong signature, not a distinct message, so a caller can't
    use the response to tell "unconfigured" apart from "wrong secret."

    Reads the raw body via request.body() before the route handler parses
    it as JSON — Starlette caches the body after the first read, so the
    route's Pydantic body model still parses correctly afterward.
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.webhook_secret is None:
        logger.error(
            "webhook_secret_not_configured",
            extra={"organization_id": organization_id},
        )
        raise HTTPException(status_code=401, detail="Invalid or missing webhook signature")

    signature = request.headers.get("X-Webhook-Signature")
    body = await request.body()
    expected = hmac.new(org.webhook_secret.encode(), body, hashlib.sha256).hexdigest()

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


def require_role(role: UserRole):
    """
    Builds a dependency gating a route to a single role. Composes on top of
    require_current_user rather than re-querying the DB itself — that
    dependency already reloads User fresh on every request (see its
    docstring), so current_user.role read here is already live; a role
    change (scripts/set_user_role.py) takes effect on the very next
    request, no token refresh or revocation needed, same as is_active.
    """

    def _check(current_user: User = Depends(require_current_user)) -> User:
        if current_user.role != role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return _check


def get_current_org_id(current_user: User = Depends(require_current_user)) -> int:
    """
    Epoch 10 (multi-tenancy). Same shape as require_role() above — composes
    on require_current_user rather than trusting a JWT claim, so
    current_user.organization_id read here is already the live value from
    the freshly-reloaded User row; moving a user to a different org takes
    effect on the very next request, no token refresh needed, same
    reasoning as role/is_active.

    Not wired into any route yet (Epoch 10 PR 3) — added standalone so
    later PRs can start depending on it without a schema/route change
    landing in the same commit.
    """
    return current_user.organization_id
