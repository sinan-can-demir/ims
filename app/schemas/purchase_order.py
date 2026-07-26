# app/schemas/purchase_order.py

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PurchaseOrderStatus


class PurchaseOrderLineCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    quantity: int = Field(gt=0)
    unit_cost: float | None = Field(default=None, ge=0)


class PurchaseOrderLineUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    quantity: int = Field(gt=0)
    unit_cost: float | None = Field(default=None, ge=0)


class PurchaseOrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purchase_order_id: int
    product_id: int
    quantity: int
    unit_cost: float | None
    created_at: datetime


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    supplier_id: int
    lines: list[PurchaseOrderLineCreate] = Field(default_factory=list)


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    status: PurchaseOrderStatus
    created_by_id: int
    created_at: datetime
    lines: list[PurchaseOrderLineResponse]
