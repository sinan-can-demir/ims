from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import EventType


class IngestRowInput(BaseModel):
    """
    One row of ingestable inventory data — the shared shape for both the CSV
    bulk-import endpoint and the webhook receiver. Mirrors
    InventoryEventCreate's event_id/quantity constraints, but takes a SKU
    instead of an internal product_id, since external sources know products
    by SKU, not our primary key.
    """

    sku: str = Field(min_length=1, max_length=100)
    event_type: EventType
    quantity: int
    event_id: str = Field(min_length=1, max_length=100)
    # Optional, additive -- see InventoryEvent.unit_price's model comment.
    # Neither existing caller (CSV import, webhook) sets this; a future
    # POS connector will.
    unit_price: float | None = Field(default=None, ge=0)

    @field_validator("quantity")
    @classmethod
    def quantity_not_zero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Quantity cannot be zero")
        return v


class IngestRowResult(BaseModel):
    row_number: int
    event_id: str | None = None
    status: Literal["success", "failed"]
    error: str | None = None


class IngestResponse(BaseModel):
    rows_processed: int
    rows_succeeded: int
    rows_failed: int
    results: list[IngestRowResult]
