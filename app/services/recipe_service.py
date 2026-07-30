# app/services/recipe_service.py

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateRecipeItemError,
    ProductNotFoundError,
    RecipeItemNotFoundError,
    SelfReferentialRecipeError,
)
from app.core.logging import logger
from app.models.product import Product
from app.models.recipe_item import RecipeItem
from app.schemas.recipe import RecipeItemCreate


def _get_product_or_raise(db: Session, product_id: int, organization_id: int = 1) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.organization_id == organization_id)
        .first()
    )
    if not product:
        raise ProductNotFoundError(product_id)
    return product


def create_recipe_item(
    db: Session, recipe_item: RecipeItemCreate, organization_id: int = 1
) -> RecipeItem:
    if recipe_item.finished_product_id == recipe_item.component_product_id:
        raise SelfReferentialRecipeError()

    _get_product_or_raise(db, recipe_item.finished_product_id, organization_id)
    _get_product_or_raise(db, recipe_item.component_product_id, organization_id)

    new_item = RecipeItem(
        finished_product_id=recipe_item.finished_product_id,
        component_product_id=recipe_item.component_product_id,
        quantity=recipe_item.quantity,
        organization_id=organization_id,
    )

    try:
        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        logger.info(
            "recipe_item_created",
            extra={
                "finished_product_id": recipe_item.finished_product_id,
                "component_product_id": recipe_item.component_product_id,
                "quantity": recipe_item.quantity,
            },
        )

        return new_item

    except IntegrityError:
        db.rollback()
        raise DuplicateRecipeItemError(
            recipe_item.finished_product_id, recipe_item.component_product_id
        )


def list_recipe_items(
    db: Session, finished_product_id: int, organization_id: int = 1
) -> list[RecipeItem]:
    _get_product_or_raise(db, finished_product_id, organization_id)
    return (
        db.query(RecipeItem)
        .filter(
            RecipeItem.finished_product_id == finished_product_id,
            RecipeItem.organization_id == organization_id,
        )
        .order_by(RecipeItem.id.asc())
        .all()
    )


def update_recipe_item_quantity(
    db: Session, recipe_item_id: int, quantity: int, organization_id: int = 1
) -> RecipeItem:
    item = (
        db.query(RecipeItem)
        .filter(RecipeItem.id == recipe_item_id, RecipeItem.organization_id == organization_id)
        .first()
    )
    if not item:
        raise RecipeItemNotFoundError(recipe_item_id)

    item.quantity = quantity
    db.commit()
    db.refresh(item)
    return item


def delete_recipe_item(db: Session, recipe_item_id: int, organization_id: int = 1) -> None:
    item = (
        db.query(RecipeItem)
        .filter(RecipeItem.id == recipe_item_id, RecipeItem.organization_id == organization_id)
        .first()
    )
    if not item:
        raise RecipeItemNotFoundError(recipe_item_id)

    db.delete(item)
    db.commit()
