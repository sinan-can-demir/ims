# tests/test_recipes.py

import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from app.models.product import Product
from app.models.recipe_item import RecipeItem

from .utils import create_product, purchase


def _sale(client, product_id, quantity, event_id=None):
    event_id = event_id or f"evt-{uuid.uuid4()}"
    return client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": "SALE",
            "quantity": quantity,
            "event_id": event_id,
        },
    )


def _quantity(client, product_id):
    return client.get(f"/api/inventory/{product_id}").json()["quantity"]


def _recipe_item(client, finished_product_id, component_product_id, quantity):
    return client.post(
        "/api/recipes",
        json={
            "finished_product_id": finished_product_id,
            "component_product_id": component_product_id,
            "quantity": quantity,
        },
    )


# ---------------------------------------------------------------------------
# Recipe item CRUD
# ---------------------------------------------------------------------------


def test_create_recipe_item(client):
    dish = create_product(client, "Burger")
    ingredient = create_product(client, "Bun")

    response = _recipe_item(client, dish["id"], ingredient["id"], 2)

    assert response.status_code == 201
    body = response.json()
    assert body["finished_product_id"] == dish["id"]
    assert body["component_product_id"] == ingredient["id"]
    assert body["quantity"] == 2


def test_recipe_item_rejects_self_reference(client):
    dish = create_product(client, "Burger")

    response = _recipe_item(client, dish["id"], dish["id"], 1)

    assert response.status_code == 400


def test_recipe_item_rejects_duplicate_pair(client):
    dish = create_product(client, "Burger")
    ingredient = create_product(client, "Bun")

    first = _recipe_item(client, dish["id"], ingredient["id"], 1)
    assert first.status_code == 201

    second = _recipe_item(client, dish["id"], ingredient["id"], 2)
    assert second.status_code == 409


def test_recipe_item_rejects_unknown_product(client):
    dish = create_product(client, "Burger")

    response = _recipe_item(client, dish["id"], 999999, 1)

    assert response.status_code == 404


def test_list_recipe_items(client):
    dish = create_product(client, "Burger")
    bun = create_product(client, "Bun")
    patty = create_product(client, "Patty")

    _recipe_item(client, dish["id"], bun["id"], 1)
    _recipe_item(client, dish["id"], patty["id"], 2)

    response = client.get(f"/api/recipes/{dish['id']}")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert {item["component_product_id"] for item in items} == {bun["id"], patty["id"]}


def test_update_recipe_item_quantity(client):
    dish = create_product(client, "Burger")
    ingredient = create_product(client, "Bun")
    created = _recipe_item(client, dish["id"], ingredient["id"], 1).json()

    response = client.patch(f"/api/recipes/{created['id']}", json={"quantity": 3})

    assert response.status_code == 200
    assert response.json()["quantity"] == 3


def test_delete_recipe_item(client):
    dish = create_product(client, "Burger")
    ingredient = create_product(client, "Bun")
    created = _recipe_item(client, dish["id"], ingredient["id"], 1).json()

    response = client.delete(f"/api/recipes/{created['id']}")
    assert response.status_code == 204

    listed = client.get(f"/api/recipes/{dish['id']}").json()
    assert listed == []


# ---------------------------------------------------------------------------
# Cascade behavior — the actual feature
# ---------------------------------------------------------------------------


def test_selling_dish_consumes_ingredients(client):
    dish = create_product(client, "Burger")
    bun = create_product(client, "Bun")
    patty = create_product(client, "Patty")

    _recipe_item(client, dish["id"], bun["id"], 1)
    _recipe_item(client, dish["id"], patty["id"], 2)

    purchase(client, dish["id"], 10)
    purchase(client, bun["id"], 20)
    purchase(client, patty["id"], 20)

    response = _sale(client, dish["id"], 3)
    assert response.status_code == 201

    assert _quantity(client, dish["id"]) == 7
    assert _quantity(client, bun["id"]) == 17  # 20 - (1 * 3)
    assert _quantity(client, patty["id"]) == 14  # 20 - (2 * 3)


def test_dish_without_recipe_has_no_cascade(client):
    dish = create_product(client, "Plain Item")
    purchase(client, dish["id"], 10)

    response = _sale(client, dish["id"], 4)

    assert response.status_code == 201
    assert _quantity(client, dish["id"]) == 6


def test_cascade_is_atomic_with_dish_sale(client):
    """
    If an ingredient can't cover the cascade, the whole sale (dish +
    ingredients) must fail together — the dish's own stock must not be
    decremented either.
    """
    dish = create_product(client, "Burger")
    bun = create_product(client, "Bun")

    _recipe_item(client, dish["id"], bun["id"], 5)

    purchase(client, dish["id"], 10)
    purchase(client, bun["id"], 3)  # not enough for 5 * quantity_sold

    response = _sale(client, dish["id"], 1)

    assert response.status_code == 400
    assert _quantity(client, dish["id"]) == 10  # unchanged, not partially applied
    assert _quantity(client, bun["id"]) == 3  # unchanged


def test_idempotent_dish_sale_does_not_double_cascade(client):
    dish = create_product(client, "Burger")
    bun = create_product(client, "Bun")

    _recipe_item(client, dish["id"], bun["id"], 1)

    purchase(client, dish["id"], 10)
    purchase(client, bun["id"], 10)

    payload_event_id = "evt-dish-sale-1"
    first = _sale(client, dish["id"], 2, event_id=payload_event_id)
    assert first.status_code == 201

    second = _sale(client, dish["id"], 2, event_id=payload_event_id)
    assert second.status_code == 201

    assert _quantity(client, dish["id"]) == 8
    assert _quantity(client, bun["id"]) == 8  # decremented once, not twice


@pytest.mark.postgres
def test_recipe_item_composite_fk_rejects_cross_org_component_product(db, second_org):
    """
    Each of recipe_items' two composite FKs independently forces its
    product to share the recipe_item row's org — this covers
    component_product_id, the sibling test covers finished_product_id.
    See migrations/versions/688eb809961b.
    """
    finished = Product(organization_id=1, name="Dish", sku=f"sku-{uuid.uuid4()}")
    org2_component = Product(
        organization_id=second_org.id, name="Org2 Ingredient", sku=f"sku-{uuid.uuid4()}"
    )
    db.add_all([finished, org2_component])
    db.commit()
    db.refresh(finished)
    db.refresh(org2_component)

    db.add(
        RecipeItem(
            organization_id=1,
            finished_product_id=finished.id,
            component_product_id=org2_component.id,
            quantity=1,
        )
    )
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()


@pytest.mark.postgres
def test_recipe_item_composite_fk_rejects_cross_org_finished_product(db, second_org):
    org2_finished = Product(
        organization_id=second_org.id, name="Org2 Dish", sku=f"sku-{uuid.uuid4()}"
    )
    component = Product(organization_id=1, name="Ingredient", sku=f"sku-{uuid.uuid4()}")
    db.add_all([org2_finished, component])
    db.commit()
    db.refresh(org2_finished)
    db.refresh(component)

    db.add(
        RecipeItem(
            organization_id=1,
            finished_product_id=org2_finished.id,
            component_product_id=component.id,
            quantity=1,
        )
    )
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()
