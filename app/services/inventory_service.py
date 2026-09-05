from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InsufficientInventoryError, InvalidEventError, ProductNotFoundError
from app.core.logging import logger
from app.models.enums import EventType
from app.models.inventory_event import InventoryEvent
from app.models.inventory_state import InventoryState
from app.models.product import Product
from app.models.recipe_item import RecipeItem


def normalize_quantity(event_type: EventType, quantity: int) -> int:
    if quantity == 0:
        raise InvalidEventError("Quantity cannot be zero")

    if event_type in [EventType.PURCHASE, EventType.RETURN]:
        if quantity < 0:
            raise InvalidEventError(f"{event_type.value} quantity must be positive")
        return quantity

    if event_type in [EventType.SALE, EventType.DAMAGE, EventType.WASTE]:
        if quantity < 0:
            raise InvalidEventError(f"{event_type.value} quantity must be positive")
        return -quantity

    if event_type == EventType.ADJUSTMENT:
        return quantity

    raise InvalidEventError("Unsupported event type")


def get_inventory(db: Session, product_id: int, organization_id: int = 1) -> int:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.organization_id == organization_id)
        .first()
    )
    if not product:
        raise ProductNotFoundError(product_id)
    # organization_id here is defense-in-depth, not closing a live gap —
    # InventoryState.product_id is already confirmed to belong to this org
    # by the Product lookup above, and product_id is globally unique
    # (one InventoryState row per product), so a cross-org match was
    # never actually reachable. Explicit anyway, matching this codebase's
    # "verify the invariant, don't just assume it" discipline (Epoch 10
    # PR 16, #152's grep sweep).
    state = (
        db.query(InventoryState)
        .filter(
            InventoryState.product_id == product_id,
            InventoryState.organization_id == organization_id,
        )
        .first()
    )
    return state.quantity if state else 0


def _apply_event(
    db: Session,
    product_id: int,
    event_type: EventType,
    quantity: int,
    event_id: str,
    created_by_id: int | None,
    organization_id: int,
    unit_price: float | None = None,
) -> tuple[InventoryEvent, bool]:
    """
    Core event application — idempotency check, oversell guard, insert
    event, update the projection. Flushes but never commits: the caller
    controls the transaction boundary, so record_event's recipe/BOM
    cascade (selling a dish also consuming its ingredients) can be applied
    as one atomic transaction with the triggering event, instead of
    partially applying if an ingredient runs out partway through.

    Returns (event, created) — created is False for an idempotent replay
    of an existing event_id, in which case no cascade should run either.
    """
    existing_event = (
        db.query(InventoryEvent)
        .filter(
            InventoryEvent.event_id == event_id,
            InventoryEvent.organization_id == organization_id,
        )
        .first()
    )
    if existing_event:
        logger.info("inventory_event_duplicate", extra={"event_id": event_id})
        return existing_event, False

    delta = normalize_quantity(event_type, quantity)

    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.organization_id == organization_id)
        .first()
    )
    if not product:
        raise ProductNotFoundError(product_id)

    # Lock inventory state row for update or create if not exists.
    # organization_id is defense-in-depth here too, same reasoning as
    # get_inventory() above — product_id already confirmed to belong to
    # this org by the Product lookup just above, so this was never
    # actually reachable cross-org.
    state = (
        db.query(InventoryState)
        .filter(
            InventoryState.product_id == product_id,
            InventoryState.organization_id == organization_id,
        )
        .with_for_update()  # Lock the row
        .first()
    )

    if state is None:
        state = InventoryState(product_id=product_id, quantity=0, organization_id=organization_id)
        db.add(state)
        db.flush()

    # Calculate new inventory level
    new_quantity = state.quantity + delta
    if new_quantity < 0 and event_type in [EventType.SALE, EventType.DAMAGE, EventType.WASTE]:
        logger.warning(
            "inventory_oversell_blocked",
            extra={
                "product_id": product_id,
                "attempted_quantity": delta,
                "current_quantity": state.quantity,
            },
        )

        raise InsufficientInventoryError(product_id, state.quantity, delta)

    event = InventoryEvent(
        product_id=product_id,
        event_type=event_type,
        quantity=delta,
        event_id=event_id,
        created_by_id=created_by_id,
        organization_id=organization_id,
        unit_price=unit_price,
    )

    db.add(event)
    state.quantity = new_quantity
    db.flush()

    logger.info(
        "inventory_event_created",
        extra={
            "product_id": product_id,
            "event_type": event_type.value,
            "quantity": delta,
            "event_id": event_id,
        },
    )

    return event, True


def _cascade_recipe_consumption(
    db: Session,
    finished_product_id: int,
    dishes_sold: int,
    source_event_id: str,
    created_by_id: int | None,
    organization_id: int,
) -> None:
    """
    Selling a dish also consumes its recipe/BOM ingredients. Cascaded
    ingredient events are recorded as SALE (not a dedicated event type) so
    that ingredient-level demand forecasting/restock — which sums SALE
    outflow per product — picks up recipe-driven demand automatically,
    with zero extra plumbing in forecast_service.py/restock_service.py.
    One level deep only: component products are assumed to be raw
    ingredients, not dishes with their own recipe.

    organization_id here is defense-in-depth, not closing a live gap —
    recipe_items' composite FK already forces any row referencing
    finished_product_id to share that product's own org, so a cross-org
    RecipeItem match was never actually reachable. Explicit anyway
    (Epoch 10 PR 16, #152's grep sweep).
    """
    recipe_items = (
        db.query(RecipeItem)
        .filter(
            RecipeItem.finished_product_id == finished_product_id,
            RecipeItem.organization_id == organization_id,
        )
        .all()
    )
    for item in recipe_items:
        component_event_id = f"{source_event_id}:component:{item.component_product_id}"
        _apply_event(
            db,
            item.component_product_id,
            EventType.SALE,
            item.quantity * dishes_sold,
            component_event_id,
            created_by_id,
            organization_id,
        )


def record_event(
    db: Session,
    product_id: int,
    event_type: EventType,
    quantity: int,
    event_id: str,
    created_by_id: int | None = None,
    organization_id: int = 1,
    unit_price: float | None = None,
) -> InventoryEvent:
    try:
        event, created = _apply_event(
            db,
            product_id,
            event_type,
            quantity,
            event_id,
            created_by_id,
            organization_id,
            unit_price,
        )

        if created and event_type == EventType.SALE:
            _cascade_recipe_consumption(
                db, product_id, quantity, event_id, created_by_id, organization_id
            )

        db.commit()
        db.refresh(event)

        return event

    except IntegrityError:
        db.rollback()

        logger.warning("inventory_event_integrity_error", extra={"event_id": event_id})

        # Check if the failure was due to a duplicate event_id (idempotency)
        existing_event = (
            db.query(InventoryEvent)
            .filter(
                InventoryEvent.event_id == event_id,
                InventoryEvent.organization_id == organization_id,
            )
            .first()
        )

        # If the event already exists, return it instead of raising an error
        if existing_event:
            return existing_event

        # If the event doesn't exist, the failure was due to another reason (e.g. DB error)
        raise

    except Exception:
        # Any other failure (e.g. InsufficientInventoryError from the
        # triggering event itself or a recipe/BOM cascade ingredient) means
        # this call's _apply_event flushes must not survive — a session
        # left with a flushed-but-uncommitted dish sale, with no explicit
        # rollback, can still be visible to whatever reuses that same
        # session next (proven by a real test failure, not a theoretical
        # gap: the atomicity test below caught partial cascade application
        # surviving until the next call on the same session). Relying on
        # the caller's session.close() to implicitly roll back isn't
        # enough to guarantee this.
        db.rollback()
        raise
