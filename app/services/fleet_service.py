# app/services/fleet_service.py

from sqlalchemy.orm import Session

from app.models.product import Product
from app.services.inventory_service import get_inventory
from app.services.restock_service import get_restock_recommendation


def get_fleet_status(db: Session) -> list[dict]:
    """
    Portfolio-wide status across every product — current inventory plus
    restock urgency, in one call. Powers fleet-wide dashboard views (the
    product selector, the Fleet Overview page) that need every product at
    a glance, unlike get_restock_recommendation()'s one-product view.

    A product with no trained forecast model yet must not fail the whole
    fleet query — forecast() raises FileNotFoundError per product, so
    that case is caught here and reported as urgency "NO_FORECAST" with
    real inventory still populated, instead of the caller getting nothing
    for the entire fleet because one product hasn't been trained yet.
    """
    products = db.query(Product).order_by(Product.name.asc()).all()

    statuses = []
    for product in products:
        try:
            status = get_restock_recommendation(db, product.id)
        except FileNotFoundError:
            status = {
                "product_id": product.id,
                "current_inventory": get_inventory(db, product.id),
                "projected_demand_7d": None,
                "safety_stock": None,
                "recommended_order_qty": None,
                "days_of_stock_remaining": None,
                "urgency": "NO_FORECAST",
            }
        statuses.append({"name": product.name, "sku": product.sku, **status})

    return statuses
