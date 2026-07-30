# dashboard/recipe_actions.py
#
# Mutating recipe/BOM operations, kept separate from dashboard/data.py's
# cached read-only loaders — these must never be @st.cache_data'd (each
# click should actually run). Calls the same service layer the API uses
# (app/services/recipe_service.py), in-process, same pattern as
# dashboard/admin_actions.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.schemas.recipe import RecipeItemCreate
from app.services.recipe_service import (
    create_recipe_item,
    delete_recipe_item,
    update_recipe_item_quantity,
)


def add_recipe_item(
    finished_product_id: int, component_product_id: int, quantity: int, organization_id: int
) -> None:
    db = SessionLocal()
    try:
        create_recipe_item(
            db,
            RecipeItemCreate(
                finished_product_id=finished_product_id,
                component_product_id=component_product_id,
                quantity=quantity,
            ),
            organization_id,
        )
    finally:
        db.close()


def update_recipe_item(recipe_item_id: int, quantity: int, organization_id: int) -> None:
    db = SessionLocal()
    try:
        update_recipe_item_quantity(db, recipe_item_id, quantity, organization_id)
    finally:
        db.close()


def remove_recipe_item(recipe_item_id: int, organization_id: int) -> None:
    db = SessionLocal()
    try:
        delete_recipe_item(db, recipe_item_id, organization_id)
    finally:
        db.close()
