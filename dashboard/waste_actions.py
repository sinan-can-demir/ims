# dashboard/waste_actions.py
#
# Mutating waste-logging operation, kept separate from dashboard/data.py's
# cached read-only loaders — these must never be @st.cache_data'd. Calls
# the same service layer the API uses, in-process, same pattern as
# dashboard/po_actions.py / dashboard/recipe_actions.py.

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.enums import EventType
from app.services.inventory_service import record_event


def log_waste(product_id: int, quantity: int, actor_id: int, organization_id: int) -> None:
    db = SessionLocal()
    try:
        record_event(
            db,
            product_id,
            EventType.WASTE,
            quantity,
            str(uuid.uuid4()),
            actor_id,
            organization_id,
        )
    finally:
        db.close()
