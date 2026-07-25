# app/schemas/inventory_event.py

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import EventType


class InventoryEventCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    event_type: EventType
    quantity: int
    event_id: str = Field(min_length=1, max_length=100)

    @field_validator("quantity")
    @classmethod
    def quantity_not_zero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Quantity cannot be zero")
        return v


class InventoryEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    event_type: EventType
    quantity: int
    event_id: str
    created_by_id: int | None
    created_at: datetime
