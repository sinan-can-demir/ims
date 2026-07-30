from collections import defaultdict

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.inventory_event import InventoryEvent
from app.models.inventory_state import InventoryState


def rebuild_inventory_state(db: Session, organization_id: int = 1) -> dict:
    """
    Rebuilds the inventory_state projection from inventory_events, scoped
    to a single org. Both the events read and the InventoryState delete
    must filter by organization_id — before this, a full-table delete
    with no filter wiped every org's projection the moment any org's
    admin ran replay, not just the caller's own (Epoch 10 PR 11, #147).

    Returns a small summary for debugging/admin use.
    """
    # Get this org's events in chronological order
    events = (
        db.query(InventoryEvent)
        .filter(InventoryEvent.organization_id == organization_id)
        .order_by(InventoryEvent.created_at.asc(), InventoryEvent.id.asc())
        .all()
    )

    # Start fresh — only this org's projection rows
    db.query(InventoryState).filter(InventoryState.organization_id == organization_id).delete()

    # Aggregate quantities by product_id
    quantities = defaultdict(int)

    # Process events in order to rebuild state
    for event in events:
        quantities[event.product_id] += event.quantity

    # Create new InventoryState rows based on aggregated quantities
    rebuilt_rows = []

    # Append new rows for products that have events
    for product_id, quantity in quantities.items():
        rebuilt_rows.append(
            InventoryState(
                product_id=product_id, quantity=quantity, organization_id=organization_id
            )
        )

    # Bulk insert new state rows
    if rebuilt_rows:
        db.add_all(rebuilt_rows)

    # Commit the transaction to save changes
    db.commit()
    logger.info(
        "inventory_replay_completed",
        extra={"events_processed": len(events), "products_rebuilt": len(rebuilt_rows)},
    )

    # Return summary of the rebuild process
    return {
        "events_processed": len(events),
        "products_rebuilt": len(rebuilt_rows),
    }
