from pydantic import BaseModel, field_validator

from app.core.security import MAX_PASSWORD_BYTES


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- auth scheme label, not a credential


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str

    @field_validator("password")
    @classmethod
    def password_within_bounds(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
        return v


class RegisterResponse(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    organization_id: int


class BootstrapStatusResponse(BaseModel):
    needs_registration: bool
