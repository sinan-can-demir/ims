# dashboard/po_actions.py
#
# Mutating purchase-order operations, kept separate from dashboard/data.py's
# cached read-only loaders — these must never be @st.cache_data'd. Calls
# the same service layer the API uses, in-process, same pattern as
# dashboard/admin_actions.py / dashboard/recipe_actions.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.schemas.purchase_order import PurchaseOrderLineCreate
from app.schemas.supplier import SupplierCreate
from app.services.purchase_order_service import (
    add_purchase_order_line,
    create_purchase_order,
    generate_draft_from_forecast,
    receive_purchase_order,
    submit_purchase_order,
)
from app.services.supplier_service import create_supplier


def add_supplier(name: str, contact_email: str | None, organization_id: int) -> None:
    db = SessionLocal()
    try:
        create_supplier(db, SupplierCreate(name=name, contact_email=contact_email), organization_id)
    finally:
        db.close()


def create_po(
    supplier_id: int,
    product_id: int,
    quantity: int,
    actor_id: int,
    organization_id: int,
    unit_cost: float | None = None,
) -> None:
    db = SessionLocal()
    try:
        create_purchase_order(
            db,
            supplier_id,
            actor_id,
            [
                PurchaseOrderLineCreate(
                    product_id=product_id, quantity=quantity, unit_cost=unit_cost
                )
            ],
            organization_id,
        )
    finally:
        db.close()


def add_line(
    po_id: int,
    product_id: int,
    quantity: int,
    organization_id: int,
    unit_cost: float | None = None,
) -> dict:
    """
    Returns a plain dict (not the ORM object) built while the session is
    still open -- previous_unit_cost/price_increased are transient
    attributes add_purchase_order_line() sets, not mapped columns, and
    the caller (the dashboard view, to decide whether to show a
    price-creep warning) needs them after this function's own session is
    already closed.
    """
    db = SessionLocal()
    try:
        line = add_purchase_order_line(
            db,
            po_id,
            PurchaseOrderLineCreate(product_id=product_id, quantity=quantity, unit_cost=unit_cost),
            organization_id,
        )
        return {
            "product_id": line.product_id,
            "unit_cost": float(line.unit_cost) if line.unit_cost is not None else None,
            "previous_unit_cost": (
                float(line.previous_unit_cost) if line.previous_unit_cost is not None else None
            ),
            "price_increased": line.price_increased,
        }
    finally:
        db.close()


def submit_po(po_id: int, actor_id: int, organization_id: int) -> None:
    db = SessionLocal()
    try:
        submit_purchase_order(db, po_id, actor_id, organization_id)
    finally:
        db.close()


def receive_po(po_id: int, actor_id: int, organization_id: int) -> None:
    db = SessionLocal()
    try:
        receive_purchase_order(db, po_id, actor_id, organization_id)
    finally:
        db.close()


def generate_po(product_id: int, supplier_id: int, actor_id: int, organization_id: int) -> None:
    db = SessionLocal()
    try:
        generate_draft_from_forecast(db, product_id, supplier_id, actor_id, organization_id)
    finally:
        db.close()
