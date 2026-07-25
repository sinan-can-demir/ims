from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import create_access_token
from app.database import get_db
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth_service import authenticate_user

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.email, credentials.password)
    token = create_access_token(user)
    return TokenResponse(access_token=token)
