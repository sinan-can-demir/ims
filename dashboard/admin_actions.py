# dashboard/admin_actions.py
#
# Mutating admin operations, kept separate from dashboard/data.py's
# cached read-only loaders — these must never be @st.cache_data'd (each
# click should actually run), and each opens/closes its own session the
# same way, mirroring app/api/inventory.py's replay/export routes
# (including the log_action audit entry) since the dashboard bypasses the
# HTTP API entirely and calls services in-process.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.services.audit_service import log_action
from app.services.export_service import export_inventory_events
from app.services.replay_service import rebuild_inventory_state


def run_replay(actor_id: int, organization_id: int) -> dict:
    db = SessionLocal()
    try:
        summary = rebuild_inventory_state(db, organization_id)
        log_action(
            db,
            actor_id,
            "replay",
            detail=f"events_processed={summary['events_processed']}",
            organization_id=organization_id,
        )
        return summary
    finally:
        db.close()


def run_export(actor_id: int) -> dict:
    db = SessionLocal()
    try:
        result = export_inventory_events(db, incremental=True)
        log_action(db, actor_id, "export", detail=f"rows_exported={result['rows_exported']}")
        return result
    finally:
        db.close()
