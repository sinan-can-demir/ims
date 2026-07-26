# app/schemas/supplier.py

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str = Field(min_length=1, max_length=255)
    # Plain str, not EmailStr — matches app/schemas/user.py's email field,
    # no email-validator dependency in requirements.txt.
    contact_email: str | None = Field(default=None, max_length=255)


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    contact_email: str | None
    created_at: datetime
