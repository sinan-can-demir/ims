# app/schemas/recipe.py

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RecipeItemCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    finished_product_id: int
    component_product_id: int
    quantity: int = Field(gt=0)


class RecipeItemUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    quantity: int = Field(gt=0)


class RecipeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    finished_product_id: int
    component_product_id: int
    quantity: int
    created_at: datetime
