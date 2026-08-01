from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import create_access_token
from app.database import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse
from app.services.auth_service import authenticate_user, register_first_user

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.email, credentials.password)
    token = create_access_token(user)
    return TokenResponse(access_token=token)


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
