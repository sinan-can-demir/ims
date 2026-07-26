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
from app.models.enums import PurchaseOrderStatus
from app.models.inventory_event import InventoryEvent
from app.services.forecast_service import forecast
from app.services.inventory_service import get_inventory
from app.services.product_service import list_products
from app.services.purchase_order_service import list_purchase_order_lines, list_purchase_orders
from app.services.restock_service import get_restock_recommendation
from app.services.supplier_service import list_suppliers

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


@st.cache_data(ttl=CACHE_TTL)
def load_inventory(product_id: int) -> int:
    return _get_inventory(product_id)


@st.cache_data(ttl=CACHE_TTL)
def load_restock(product_id: int) -> dict:
    return _get_restock(product_id)


@st.cache_data(ttl=CACHE_TTL)
def load_forecast(product_id: int) -> pd.DataFrame:
    return forecast(product_id, days=7)


@st.cache_data(ttl=CACHE_TTL)
def load_events(product_id: int) -> list[dict]:
    return _get_events(product_id)


def _list_products() -> list[dict]:
    db = SessionLocal()
    try:
        return [{"id": p.id, "name": p.name, "sku": p.sku} for p in list_products(db)]
    finally:
        db.close()


def _list_suppliers() -> list[dict]:
    db = SessionLocal()
    try:
        return [{"id": s.id, "name": s.name} for s in list_suppliers(db)]
    finally:
        db.close()


def _list_purchase_orders(status: str | None) -> list[dict]:
    db = SessionLocal()
    try:
        status_enum = PurchaseOrderStatus(status) if status else None
        orders = list_purchase_orders(db, status_enum)
        result = []
        for po in orders:
            lines = list_purchase_order_lines(db, po.id)
            result.append(
                {
                    "id": po.id,
                    "supplier_id": po.supplier_id,
                    "status": po.status.value,
                    "created_at": po.created_at.strftime("%Y-%m-%d %H:%M"),
                    "lines": [
                        {
                            "id": line.id,
                            "product_id": line.product_id,
                            "quantity": line.quantity,
                            "unit_cost": float(line.unit_cost) if line.unit_cost else None,
                        }
                        for line in lines
                    ],
                }
            )
        return result
    finally:
        db.close()


@st.cache_data(ttl=CACHE_TTL)
def load_products() -> list[dict]:
    return _list_products()


@st.cache_data(ttl=CACHE_TTL)
def load_suppliers() -> list[dict]:
    return _list_suppliers()


@st.cache_data(ttl=CACHE_TTL)
def load_purchase_orders(status: str | None = None) -> list[dict]:
    return _list_purchase_orders(status)
