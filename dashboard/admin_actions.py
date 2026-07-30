# dashboard/admin_actions.py
#
# Mutating admin operations, kept separate from dashboard/data.py's
# cached read-only loaders — these must never be @st.cache_data'd (each
# click should actually run), and each opens/closes its own session the
# same way, mirroring app/api/inventory.py's replay route (including the
# log_action audit entry) since the dashboard bypasses the HTTP API
# entirely and calls services in-process.
#
# run_export() lived here until Epoch 10 PR 13 (#149) — removed on
# purpose, not just deferred. The export checkpoint is inherently a
# whole-deployment, cross-org operation (see export_service.py's
# _build_base_query docstring), so a single org's admin triggering it
# from their own per-org dashboard was never the right shape once real
# multi-tenancy existed. It's an ops-only action now: `make export` /
# `python -m app.scripts.export_events`, see
# docs/deployment/self-hosted.md's "Automated data export" section.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.services.audit_service import log_action
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
