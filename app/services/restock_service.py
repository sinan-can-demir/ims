# app/services/restock_service.py

from sqlalchemy.orm import Session

from app.services.forecast_service import forecast
from app.services.inventory_service import get_inventory


def get_restock_recommendation(db: Session, product_id: int, organization_id: int = 1) -> dict:
    """
    Combine current inventory with demand forecast to produce
    an actionable restock recommendation.

    forecast() itself isn't org-scoped yet — model files aren't
    per-org-partitioned until Epoch 10 PR 15 (#151) — only the inventory
    lookup above is scoped here.
    """
    # 1. Get current inventory level
    current_qty = get_inventory(db, product_id, organization_id)

    # 2. Get 7-day demand forecast
    forecast_df = forecast(product_id, days=7)
    projected_demand = max(0, forecast_df["yhat"].clip(lower=0).sum())

    # 3. Safety stock = 20% buffer on top of projected demand
    safety_stock = round(projected_demand * 0.20)

    # 4. Recommended order quantity
    recommended_qty = max(0, round(projected_demand + safety_stock - current_qty))

    # 5. Days of stock remaining at average daily demand rate
    daily_demand = projected_demand / 7
    if daily_demand > 0:
        days_of_stock = round(current_qty / daily_demand)
    else:
        days_of_stock = 999  # no demand projected

    # 6. Urgency classification
    if current_qty == 0:
        urgency = "STOCKOUT"
    elif days_of_stock < 4:
        urgency = "URGENT"
    elif days_of_stock < 7:
        urgency = "LOW"
    else:
        urgency = "OK"

    return {
        "product_id": product_id,
        "current_inventory": current_qty,
        "projected_demand_7d": round(projected_demand, 1),
        "safety_stock": safety_stock,
        "recommended_order_qty": recommended_qty,
        "days_of_stock_remaining": days_of_stock,
        "urgency": urgency,
    }
