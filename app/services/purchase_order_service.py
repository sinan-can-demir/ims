# app/services/purchase_order_service.py

from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidPurchaseOrderStateError,
    ProductNotFoundError,
    PurchaseOrderLineNotFoundError,
    PurchaseOrderNotFoundError,
    RestockNotNeededError,
)
from app.core.logging import logger
from app.models.enums import EventType, PurchaseOrderStatus
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.schemas.purchase_order import PurchaseOrderLineCreate
from app.services.audit_service import log_action
from app.services.inventory_service import record_event
from app.services.restock_service import get_restock_recommendation
from app.services.supplier_service import get_supplier


def _get_product_or_raise(db: Session, product_id: int, organization_id: int = 1) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.organization_id == organization_id)
        .first()
    )
    if not product:
        raise ProductNotFoundError(product_id)
    return product


def get_purchase_order(
    db: Session, purchase_order_id: int, organization_id: int = 1
) -> PurchaseOrder:
    po = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.organization_id == organization_id,
        )
        .first()
    )
    if not po:
        raise PurchaseOrderNotFoundError(purchase_order_id)
    return po


def list_purchase_order_lines(
    db: Session, purchase_order_id: int, organization_id: int = 1
) -> list[PurchaseOrderLine]:
    return (
        db.query(PurchaseOrderLine)
        .filter(
            PurchaseOrderLine.purchase_order_id == purchase_order_id,
            PurchaseOrderLine.organization_id == organization_id,
        )
        .order_by(PurchaseOrderLine.id.asc())
        .all()
    )


def list_purchase_orders(
    db: Session, status: PurchaseOrderStatus | None = None, organization_id: int = 1
) -> list[PurchaseOrder]:
    query = db.query(PurchaseOrder).filter(PurchaseOrder.organization_id == organization_id)
    if status is not None:
        query = query.filter(PurchaseOrder.status == status)
    return query.order_by(PurchaseOrder.created_at.desc()).all()


def create_purchase_order(
    db: Session,
    supplier_id: int,
    created_by_id: int,
    lines: list[PurchaseOrderLineCreate],
    organization_id: int = 1,
) -> PurchaseOrder:
    get_supplier(db, supplier_id, organization_id)
    for line in lines:
        _get_product_or_raise(db, line.product_id, organization_id)

    po = PurchaseOrder(
        supplier_id=supplier_id,
        status=PurchaseOrderStatus.DRAFT,
        created_by_id=created_by_id,
        organization_id=organization_id,
    )
    db.add(po)
    db.flush()

    for line in lines:
        db.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                product_id=line.product_id,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                organization_id=organization_id,
            )
        )

    db.commit()
    db.refresh(po)

    logger.info(
        "purchase_order_created",
        extra={"purchase_order_id": po.id, "supplier_id": supplier_id, "line_count": len(lines)},
    )

    return po


def _require_draft(po: PurchaseOrder, action: str) -> None:
    if po.status != PurchaseOrderStatus.DRAFT:
        raise InvalidPurchaseOrderStateError(po.id, po.status.value, action)


def _get_last_unit_cost(db: Session, product_id: int, organization_id: int) -> float | None:
    """
    Most recent prior PO line for this product with a real (non-null) unit
    cost — the baseline `add_purchase_order_line` flags a new line's cost
    against (see `ROADMAP.md`'s "Food Cost Visibility" Phase 2). Ordered
    by id, not created_at: created_at's `server_default=func.now()` only
    has second-resolution and isn't populated until a refresh, so it's a
    weaker tiebreaker than the monotonically-increasing PK for lines
    created close together.
    """
    last_line = (
        db.query(PurchaseOrderLine)
        .filter(
            PurchaseOrderLine.product_id == product_id,
            PurchaseOrderLine.organization_id == organization_id,
            PurchaseOrderLine.unit_cost.isnot(None),
        )
        .order_by(PurchaseOrderLine.id.desc())
        .first()
    )
    return last_line.unit_cost if last_line else None


def add_purchase_order_line(
    db: Session, purchase_order_id: int, line: PurchaseOrderLineCreate, organization_id: int = 1
) -> PurchaseOrderLine:
    po = get_purchase_order(db, purchase_order_id, organization_id)
    _require_draft(po, "add a line to")
    _get_product_or_raise(db, line.product_id, organization_id)

    # Queried before inserting the new line, so this is genuinely the
    # prior line -- never the one about to be created.
    previous_unit_cost = (
        _get_last_unit_cost(db, line.product_id, organization_id)
        if line.unit_cost is not None
        else None
    )

    new_line = PurchaseOrderLine(
        purchase_order_id=purchase_order_id,
        product_id=line.product_id,
        quantity=line.quantity,
        unit_cost=line.unit_cost,
        organization_id=organization_id,
    )
    db.add(new_line)
    db.commit()
    db.refresh(new_line)

    # Transient, not a mapped column -- deliberately not persisted, just
    # carried on the returned object for this one request/response so the
    # caller (API route, dashboard) can surface a "cost went up" flag
    # without a second query. See PurchaseOrderLineResponse.
    new_line.previous_unit_cost = previous_unit_cost
    new_line.price_increased = (
        previous_unit_cost is not None
        and new_line.unit_cost is not None
        and new_line.unit_cost > previous_unit_cost
    )

    return new_line


def _get_line_or_raise(db: Session, line_id: int, organization_id: int = 1) -> PurchaseOrderLine:
    line = (
        db.query(PurchaseOrderLine)
        .filter(
            PurchaseOrderLine.id == line_id, PurchaseOrderLine.organization_id == organization_id
        )
        .first()
    )
    if not line:
        raise PurchaseOrderLineNotFoundError(line_id)
    return line


def update_purchase_order_line(
    db: Session,
    line_id: int,
    quantity: int,
    unit_cost: float | None,
    organization_id: int = 1,
) -> PurchaseOrderLine:
    line = _get_line_or_raise(db, line_id, organization_id)
    po = get_purchase_order(db, line.purchase_order_id, organization_id)
    _require_draft(po, "edit a line on")

    line.quantity = quantity
    line.unit_cost = unit_cost
    db.commit()
    db.refresh(line)
    return line


def remove_purchase_order_line(db: Session, line_id: int, organization_id: int = 1) -> None:
    line = _get_line_or_raise(db, line_id, organization_id)
    po = get_purchase_order(db, line.purchase_order_id, organization_id)
    _require_draft(po, "remove a line from")

    db.delete(line)
    db.commit()


def submit_purchase_order(
    db: Session, purchase_order_id: int, actor_id: int, organization_id: int = 1
) -> PurchaseOrder:
    po = get_purchase_order(db, purchase_order_id, organization_id)
    _require_draft(po, "submit")

    lines = list_purchase_order_lines(db, purchase_order_id, organization_id)
    if not lines:
        raise InvalidPurchaseOrderStateError(
            purchase_order_id, po.status.value, "submit (no lines)"
        )

    po.status = PurchaseOrderStatus.SUBMITTED
    db.commit()
    db.refresh(po)

    log_action(
        db,
        actor_id,
        "po_submitted",
        organization_id=organization_id,
        detail=f"purchase_order_id={purchase_order_id}",
    )

    return po


def receive_purchase_order(
    db: Session, purchase_order_id: int, actor_id: int, organization_id: int = 1
) -> PurchaseOrder:
    """
    Marks a PO received and creates one PURCHASE InventoryEvent per line,
    via the existing record_event() — reused as-is rather than a custom
    non-committing variant, since PURCHASE has no oversell-style failure
    mode (the only realistic failure is a since-deleted product, already
    checked at line-creation time). Each line's event_id
    (po-{id}-line-{id}) is deterministic, so retrying a partially-failed
    receive is safe: record_event()'s own idempotency check no-ops any
    line already applied, rather than double-counting it.
    """
    po = get_purchase_order(db, purchase_order_id, organization_id)
    if po.status != PurchaseOrderStatus.SUBMITTED:
        raise InvalidPurchaseOrderStateError(purchase_order_id, po.status.value, "receive")

    lines = list_purchase_order_lines(db, purchase_order_id, organization_id)
    for line in lines:
        record_event(
            db,
            line.product_id,
            EventType.PURCHASE,
            line.quantity,
            f"po-{purchase_order_id}-line-{line.id}",
            actor_id,
            organization_id,
        )

    po.status = PurchaseOrderStatus.RECEIVED
    db.commit()
    db.refresh(po)

    log_action(
        db,
        actor_id,
        "po_received",
        organization_id=organization_id,
        detail=f"purchase_order_id={purchase_order_id}",
    )

    return po


def generate_draft_from_forecast(
    db: Session, product_id: int, supplier_id: int, created_by_id: int, organization_id: int = 1
) -> PurchaseOrder:
    """
    Pre-fills a draft PO's single line from restock_service's existing
    recommendation for this product. Works at whatever granularity the
    caller passes a product_id for — a dish or a raw ingredient; composing
    this with recipe/BOM to expand a dish into its ingredients is a
    natural follow-up once that lands, not built in here to keep this
    self-contained.

    get_restock_recommendation() gained organization_id in Epoch 10 PR 11
    (#147) — passed through here now, closing a real pre-existing gap:
    before PR 11, a product lookup buried inside get_restock_recommendation
    always defaulted to org 1, so this route 404'd for any org-2 product
    even before purchase_order_service.py itself was org-threaded.
    """
    recommendation = get_restock_recommendation(db, product_id, organization_id)
    qty = recommendation["recommended_order_qty"]
    if qty <= 0:
        raise RestockNotNeededError(product_id, qty)

    return create_purchase_order(
        db,
        supplier_id,
        created_by_id,
        [PurchaseOrderLineCreate(product_id=product_id, quantity=qty)],
        organization_id,
    )
