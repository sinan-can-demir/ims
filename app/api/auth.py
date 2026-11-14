import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import create_access_token
from app.database import get_db
from app.schemas.auth import (
    BootstrapStatusResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.services.auth_service import authenticate_user, needs_registration, register_first_user

router = APIRouter()

# Opt-in switch for the first-run "claim the admin account" endpoints (#389).
# Off unless explicitly enabled: only the desktop/quickstart compose file
# (deploy/docker-compose.yml, the stack the desktop app launches) turns it on,
# because the desktop's first-run wizard has no other way to create an account.
# On a server deployment, anyone who could reach /api/auth/register before the
# operator ran scripts/create_user.py could claim the admin account.
_BOOTSTRAP_REGISTER_ENV = "IMS_ENABLE_BOOTSTRAP_REGISTER"
_TRUTHY = {"1", "true", "yes", "on"}


def bootstrap_register_enabled() -> bool:
    """Read on every call (not at import) so it follows the process env."""
    return os.getenv(_BOOTSTRAP_REGISTER_ENV, "").strip().lower() in _TRUTHY


def require_bootstrap_register_enabled() -> None:
    # 404, not 403: when disabled these routes should look like they don't
    # exist, not advertise that a bootstrap path is there to be unlocked.
    if not bootstrap_register_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


@router.post("/auth/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.email, credentials.password)
    token = create_access_token(user)
    return TokenResponse(access_token=token)


@router.get(
    "/auth/bootstrap-status",
    response_model=BootstrapStatusResponse,
    dependencies=[Depends(require_bootstrap_register_enabled)],
)
def bootstrap_status(db: Session = Depends(get_db)):
    """
    Unauthenticated on purpose — the desktop wizard (#192) calls this
    before any account (and therefore any bearer token) exists, to decide
    whether to show the first-account form at all. Reveals only a
    boolean, nothing about who, if anyone, has registered.
    """
    return BootstrapStatusResponse(needs_registration=needs_registration(db))


@router.post(
    "/auth/register",
    response_model=RegisterResponse,
    status_code=201,
    dependencies=[Depends(require_bootstrap_register_enabled)],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = register_first_user(db, payload.email, payload.password, payload.display_name)
    return RegisterResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        organization_id=user.organization_id,
    )
