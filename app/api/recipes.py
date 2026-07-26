# app/api/recipes.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recipe import RecipeItemCreate, RecipeItemResponse, RecipeItemUpdate
from app.services.recipe_service import (
    create_recipe_item,
    delete_recipe_item,
    list_recipe_items,
    update_recipe_item_quantity,
)

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.post("", response_model=RecipeItemResponse, status_code=201)
def create_recipe_item_route(recipe_item: RecipeItemCreate, db: Session = Depends(get_db)):
    """
    Adds one ingredient line to a dish's recipe/BOM: selling
    finished_product_id will consume `quantity` units of
    component_product_id per unit sold (see POST /api/inventory/events).
    """
    return create_recipe_item(db, recipe_item)


@router.get("/{finished_product_id}", response_model=list[RecipeItemResponse])
def list_recipe_items_route(finished_product_id: int, db: Session = Depends(get_db)):
    """Lists every ingredient in a dish's recipe/BOM."""
    return list_recipe_items(db, finished_product_id)


@router.patch("/{recipe_item_id}", response_model=RecipeItemResponse)
def update_recipe_item_route(
    recipe_item_id: int, update: RecipeItemUpdate, db: Session = Depends(get_db)
):
    """Updates the quantity of an existing recipe item."""
    return update_recipe_item_quantity(db, recipe_item_id, update.quantity)


@router.delete("/{recipe_item_id}", status_code=204)
def delete_recipe_item_route(recipe_item_id: int, db: Session = Depends(get_db)):
    """Removes an ingredient line from a dish's recipe/BOM."""
    delete_recipe_item(db, recipe_item_id)
