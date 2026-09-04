# tests/test_validate_exports.py

from unittest.mock import patch

from app.scripts.validate_exports import validate_exports
from app.services.export_service import export_inventory_events

from .utils import create_product, purchase


def test_validate_exports_schema_valid(client, db, export_paths):
    """
    validate_exports() must consider a real export's schema valid —
    its own hardcoded expected_columns set must match what
    export_service actually writes, including organization_id.
    """
    events_root, _ = export_paths

    product = create_product(client)
    purchase(client, product["id"], 10)

    db.expire_all()
    export_inventory_events(db, incremental=False)

    # validate_exports.py imports INVENTORY_EVENTS_ROOT into its own
    # module namespace separately from export_service — export_paths
    # only patches export_service's copy, so it must be patched here too.
    with patch("app.scripts.validate_exports.INVENTORY_EVENTS_ROOT", events_root):
        result = validate_exports(db)

    assert result["schema_valid"] is True
    assert result["row_count_match"] is True
    assert result["duplicate_event_ids"] == 0
