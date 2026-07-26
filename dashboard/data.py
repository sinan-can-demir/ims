# dashboard/data.py
#
# Cached data-loading layer for the dashboard. Every page imports from here
# rather than opening its own DB session, so caching and session handling
# stay in one place.

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.inventory_event import InventoryEvent
from app.models.recipe_item import RecipeItem
from app.services.forecast_service import forecast
from app.services.inventory_service import get_inventory
from app.services.product_service import list_products
from app.services.restock_service import get_restock_recommendation

CACHE_TTL = 300

# ---------------------------------------------------------------
# Sessions stay outside the cache layer.
# Cache only plain Python values — never ORM objects.
# ---------------------------------------------------------------


def _get_inventory(product_id: int) -> int:
    db = SessionLocal()
    try:
        return get_inventory(db, product_id)
    finally:
        db.close()


def _get_restock(product_id: int) -> dict:
    db = SessionLocal()
    try:
        return get_restock_recommendation(db, product_id)
    finally:
        db.close()


def _get_events(product_id: int) -> list[dict]:
    db = SessionLocal()
    try:
        events = (
            db.query(InventoryEvent)
            .filter(InventoryEvent.product_id == product_id)
            .order_by(InventoryEvent.created_at.desc())
            .limit(20)
            .all()
        )
        # Serialize to plain dicts here, inside the session,
        # before the session closes. Never let ORM objects
        # escape the session boundary.
        return [
            {
                "Date": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "Event Type": e.event_type.value,
                "Quantity": e.quantity,
                "Event ID": e.event_id,
            }
            for e in events
        ]
    finally:
        db.close()


def _list_products() -> list[dict]:
    db = SessionLocal()
    try:
        return [
            {"id": p.id, "name": p.name, "sku": p.sku, "unit": p.unit}
            for p in list_products(db)
        ]
    finally:
        db.close()


def _list_recipe_items(finished_product_id: int) -> list[dict]:
    db = SessionLocal()
    try:
        items = (
            db.query(RecipeItem)
            .filter(RecipeItem.finished_product_id == finished_product_id)
            .order_by(RecipeItem.id.asc())
            .all()
        )
        return [
            {
                "id": item.id,
                "component_product_id": item.component_product_id,
                "quantity": item.quantity,
            }
            for item in items
        ]
    finally:
        db.close()


@st.cache_data(ttl=CACHE_TTL)
def load_inventory(product_id: int) -> int:
    return _get_inventory(product_id)


@st.cache_data(ttl=CACHE_TTL)
def load_products() -> list[dict]:
    return _list_products()


@st.cache_data(ttl=CACHE_TTL)
def load_recipe_items(finished_product_id: int) -> list[dict]:
    return _list_recipe_items(finished_product_id)


@st.cache_data(ttl=CACHE_TTL)
def load_restock(product_id: int) -> dict:
    return _get_restock(product_id)


@st.cache_data(ttl=CACHE_TTL)
def load_forecast(product_id: int) -> pd.DataFrame:
    return forecast(product_id, days=7)


@st.cache_data(ttl=CACHE_TTL)
def load_events(product_id: int) -> list[dict]:
    return _get_events(product_id)
