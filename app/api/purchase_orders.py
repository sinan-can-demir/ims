# app/api/purchase_orders.py

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.database import get_db
from app.models.enums import PurchaseOrderStatus
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.user import User
from app.schemas.purchase_order import (
    PurchaseOrderCreate,
    PurchaseOrderLineCreate,
    PurchaseOrderLineResponse,
    PurchaseOrderLineUpdate,
    PurchaseOrderResponse,
)
from app.services.purchase_order_service import (
    add_purchase_order_line,
    create_purchase_order,
    generate_draft_from_forecast,
    get_purchase_order,
    list_purchase_order_lines,
    list_purchase_orders,
    receive_purchase_order,
    remove_purchase_order_line,
    submit_purchase_order,
    update_purchase_order_line,
)

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


def _to_response(po: PurchaseOrder, lines: list[PurchaseOrderLine]) -> PurchaseOrderResponse:
    return PurchaseOrderResponse(
        id=po.id,
        supplier_id=po.supplier_id,
        status=po.status,
        created_by_id=po.created_by_id,
        created_at=po.created_at,
        lines=[PurchaseOrderLineResponse.model_validate(line) for line in lines],
    )


@router.post("", response_model=PurchaseOrderResponse, status_code=201)
def create_purchase_order_route(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    po = create_purchase_order(db, payload.supplier_id, current_user.id, payload.lines)
    return _to_response(po, list_purchase_order_lines(db, po.id))


@router.get("", response_model=list[PurchaseOrderResponse])
def list_purchase_orders_route(
    status: PurchaseOrderStatus | None = Query(default=None),
    db: Session = Depends(get_db),
):
    orders = list_purchase_orders(db, status)
    return [_to_response(po, list_purchase_order_lines(db, po.id)) for po in orders]


@router.get("/{purchase_order_id}", response_model=PurchaseOrderResponse)
def get_purchase_order_route(purchase_order_id: int, db: Session = Depends(get_db)):
    po = get_purchase_order(db, purchase_order_id)
    return _to_response(po, list_purchase_order_lines(db, purchase_order_id))


@router.post(
    "/{purchase_order_id}/lines", response_model=PurchaseOrderLineResponse, status_code=201
)
def add_purchase_order_line_route(
    purchase_order_id: int, line: PurchaseOrderLineCreate, db: Session = Depends(get_db)
):
    return add_purchase_order_line(db, purchase_order_id, line)


@router.patch("/lines/{line_id}", response_model=PurchaseOrderLineResponse)
def update_purchase_order_line_route(
    line_id: int, update: PurchaseOrderLineUpdate, db: Session = Depends(get_db)
):
    return update_purchase_order_line(db, line_id, update.quantity, update.unit_cost)


@router.delete("/lines/{line_id}", status_code=204)
def remove_purchase_order_line_route(line_id: int, db: Session = Depends(get_db)):
    remove_purchase_order_line(db, line_id)


@router.post("/{purchase_order_id}/submit", response_model=PurchaseOrderResponse)
def submit_purchase_order_route(
    purchase_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    po = submit_purchase_order(db, purchase_order_id, current_user.id)
    return _to_response(po, list_purchase_order_lines(db, purchase_order_id))


@router.post("/{purchase_order_id}/receive", response_model=PurchaseOrderResponse)
def receive_purchase_order_route(
    purchase_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    po = receive_purchase_order(db, purchase_order_id, current_user.id)
    return _to_response(po, list_purchase_order_lines(db, purchase_order_id))


@router.post("/generate/{product_id}", response_model=PurchaseOrderResponse, status_code=201)
def generate_purchase_order_route(
    product_id: int,
    supplier_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    po = generate_draft_from_forecast(db, product_id, supplier_id, current_user.id)
    return _to_response(po, list_purchase_order_lines(db, po.id))
