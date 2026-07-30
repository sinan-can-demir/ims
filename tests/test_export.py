# tests/test_export.py


import pandas as pd

from app.services.export_service import export_inventory_events

from .utils import create_product, purchase

# ---------------------------------------------------------------------------
# Test 1 — Full export creates files and returns correct metadata
# ---------------------------------------------------------------------------


def test_full_export_creates_files(client, db, export_paths):
    """
    After creating 2 events a full export must:
    - return rows_exported == 2
    - write at least 1 parquet file to disk
    """
    events_root, _ = export_paths

    product = create_product(client)
    purchase(client, product["id"], 10)
    purchase(client, product["id"], 5)

    # expire_all() forces the fixture db session to re-read from the
    # connection rather than serve stale identity-map cache. Required
    # because the HTTP client writes through a different session.
    db.expire_all()
    result = export_inventory_events(db, incremental=False)

    assert result["rows_exported"] == 2
    assert result["files_written"] >= 1

    parquet_files = list(events_root.rglob("*.parquet"))
    assert len(parquet_files) >= 1, "Expected at least one parquet file on disk"


# ---------------------------------------------------------------------------
# Test 2 — Partition directory structure is correct
# ---------------------------------------------------------------------------


def test_partition_structure(client, db, export_paths):
    """
    Exported files must sit inside org_id=.../year=.../month=.../day=...
    directories, org_id as the outermost level (Epoch 10 PR 13, #149).
    """
    events_root, _ = export_paths

    product = create_product(client)
    purchase(client, product["id"], 20)

    db.expire_all()
    export_inventory_events(db, incremental=False)

    parquet_files = list(events_root.rglob("*.parquet"))
    assert parquet_files, "No parquet files written"

    for f in parquet_files:
        parts = f.parts
        assert any(p.startswith("org_id=") for p in parts), f"Missing org_id= in path: {f}"
        assert any(p.startswith("year=") for p in parts), f"Missing year= in path: {f}"
        assert any(p.startswith("month=") for p in parts), f"Missing month= in path: {f}"
        assert any(p.startswith("day=") for p in parts), f"Missing day= in path: {f}"
        org_idx = next(i for i, p in enumerate(parts) if p.startswith("org_id="))
        year_idx = next(i for i, p in enumerate(parts) if p.startswith("year="))
        assert org_idx < year_idx, "org_id= must be the outermost partition level"


# ---------------------------------------------------------------------------
# Test 3 — Exported parquet schema matches expected columns
# ---------------------------------------------------------------------------


def test_export_schema_columns(client, db, export_paths):
    """
    The parquet file must contain exactly the expected columns.
    No extra columns, no missing columns.
    """
    events_root, _ = export_paths

    product = create_product(client)
    purchase(client, product["id"], 15)

    db.expire_all()
    export_inventory_events(db, incremental=False)

    parquet_files = list(events_root.rglob("*.parquet"))
    assert parquet_files, "No parquet files written"

    df = pd.read_parquet(parquet_files[0])

    expected_columns = {
        "id",
        "event_id",
        "product_id",
        "event_type",
        "quantity",
        "created_at",
        "organization_id",
    }
    assert set(df.columns) == expected_columns, (
        f"Column mismatch.\n  Expected: {expected_columns}\n  Got: {set(df.columns)}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Incremental export only exports new events
# ---------------------------------------------------------------------------


def test_incremental_export_only_new_events(client, db, export_paths):
    """
    First export (2 events) writes a checkpoint.
    Second export (1 new event) must export exactly 1 row.
    """
    _, checkpoint = export_paths

    product = create_product(client)
    purchase(client, product["id"], 10)
    purchase(client, product["id"], 20)

    # First run — full baseline
    db.expire_all()
    first = export_inventory_events(db, incremental=True)
    assert first["rows_exported"] == 2
    assert first["checkpoint_updated"] is True
    assert checkpoint.exists(), "Checkpoint file must be written after first export"

    # Add one more event, then expire so the fixture db session sees it
    purchase(client, product["id"], 30)
    db.expire_all()

    # Second run — should only pick up the new event
    second = export_inventory_events(db, incremental=True)
    assert second["rows_exported"] == 1, f"Expected 1 new row, got {second['rows_exported']}"


# ---------------------------------------------------------------------------
# Test 5 — Re-running incremental with no new events exports nothing
# ---------------------------------------------------------------------------


def test_incremental_no_new_events(client, db, export_paths):
    """
    Re-running incremental export when nothing has changed must:
    - return rows_exported == 0
    - return checkpoint_updated == False
    - not crash
    """
    product = create_product(client)
    purchase(client, product["id"], 10)

    db.expire_all()
    export_inventory_events(db, incremental=True)

    # Second run — nothing new, session already up to date
    result = export_inventory_events(db, incremental=True)

    assert result["rows_exported"] == 0
    assert result["checkpoint_updated"] is False


# ---------------------------------------------------------------------------
# Test 6 — Empty export (no events in DB) is handled gracefully
# ---------------------------------------------------------------------------


def test_empty_export_no_crash(db, export_paths):
    """
    Calling export with an empty database must not raise and must
    return zero-row metadata.
    """
    result = export_inventory_events(db, incremental=False)

    assert result["rows_exported"] == 0
    assert result["files_written"] == 0
    assert result["checkpoint_updated"] is False
