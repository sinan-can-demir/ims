from pydantic import BaseModel


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


class RegisterResponse(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    organization_id: int


class BootstrapStatusResponse(BaseModel):
    needs_registration: bool
