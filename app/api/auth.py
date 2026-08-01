from fastapi import APIRouter, Depends
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


@router.post("/auth/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.email, credentials.password)
    token = create_access_token(user)
    return TokenResponse(access_token=token)


@router.get("/auth/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(db: Session = Depends(get_db)):
    """
    Unauthenticated on purpose — the desktop wizard (#192) calls this
    before any account (and therefore any bearer token) exists, to decide
    whether to show the first-account form at all. Reveals only a
    boolean, nothing about who, if anyone, has registered.
    """
    return BootstrapStatusResponse(needs_registration=needs_registration(db))


@router.post("/auth/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = register_first_user(db, payload.email, payload.password, payload.display_name)
    return RegisterResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        organization_id=user.organization_id,
    )
