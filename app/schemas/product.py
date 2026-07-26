from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str = Field(min_length=1, max_length=255)
    sku: str = Field(min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=20)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sku: str
    unit: str | None
    created_at: datetime
