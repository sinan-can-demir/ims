# tests/test_warehouse.py

import uuid

import duckdb
import pandas as pd
import pytest

from app.services.export_service import export_inventory_events
from app.services.warehouse_service import (
    _safe_path,
    build_dim_dates,
    build_dim_products,
    build_fact_table,
)

from .utils import create_product, purchase


def test_safe_path_accepts_root_itself(tmp_path):
    root = tmp_path / "warehouse"
    root.mkdir()
    assert _safe_path(root, root=root) == str(root.resolve())


def test_safe_path_accepts_child_of_root(tmp_path):
    root = tmp_path / "warehouse"
    root.mkdir()
    child = root / "dim_products.parquet"
    assert _safe_path(child, root=root) == str(child.resolve())


def test_safe_path_rejects_traversal_outside_root(tmp_path):
    root = tmp_path / "warehouse"
    root.mkdir()
    escaped = root / ".." / "secrets"
    with pytest.raises(ValueError, match="escapes expected root"):
        _safe_path(escaped, root=root)


def test_safe_path_rejects_sibling_directory(tmp_path):
    root = tmp_path / "warehouse"
    sibling = tmp_path / "other"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(ValueError, match="escapes expected root"):
        _safe_path(sibling, root=root)


def test_safe_path_rejects_unsafe_characters(tmp_path):
    root = tmp_path / "warehouse'; DROP TABLE x; --"
    root.mkdir()
    with pytest.raises(ValueError, match="unsafe characters"):
        _safe_path(root, root=root)


def test_build_dim_tables(client, db, warehouse_paths):
    # create some products via HTTP client
    create_product(client, name="Widget A")
    create_product(client, name="Widget B")

    db.expire_all()
    count = build_dim_products(db)
    assert count == 2

    df = pd.read_parquet(warehouse_paths / "dim_products.parquet")
    expected_columns = {"product_id", "name", "sku", "created_at", "organization_id"}
    assert set(df.columns) == expected_columns
    assert len(df) == 2


def test_dim_dates_structure(warehouse_paths):
    count = build_dim_dates("2026-01-01", "2026-01-31")
    assert count == 31

    df = pd.read_parquet(warehouse_paths / "dim_dates.parquet")

    expected_columns = {"date_id", "year", "month", "day", "quarter", "day_of_week", "is_weekend"}
    assert set(df.columns) == expected_columns

    # 2026-01-03 is a Saturday
    saturday = df[df["date_id"] == "2026-01-03"].iloc[0]
    assert saturday["is_weekend"]


def test_build_fact_table(client, db, warehouse_paths, export_paths):
    # create product and events
    product = create_product(client)
    purchase(client, product["id"], 50)
    purchase(client, product["id"], 30)

    # export to data lake first
    db.expire_all()
    export_inventory_events(db, incremental=False)

    # build dimensions first (fact table needs dim_products)
    db.expire_all()
    build_dim_products(db)

    # build fact table
    count = build_fact_table()
    assert count == 2


def test_build_fact_table_survives_schema_drift(client, db, warehouse_paths, export_paths):
    """
    Regression test for #210. Historically (Epoch 10 PR 13, #149) a real
    schema change added organization_id to exported parquet files — a
    pre-migration file left on disk lacks that column entirely. Without
    union_by_name=true on the events glob, DuckDB requires identical
    columns across every file it matches and throws a binder error the
    moment an old-schema file is in the mix, instead of unioning by name
    and letting the missing column read as NULL.
    """
    events_root, _ = export_paths

    product = create_product(client)
    purchase(client, product["id"], 50)

    db.expire_all()
    export_inventory_events(db, incremental=False)
    db.expire_all()
    build_dim_products(db)

    stale_df = pd.DataFrame(
        {
            "id": [999],
            "event_id": ["evt-stale"],
            "product_id": [product["id"]],
            "event_type": ["PURCHASE"],
            "quantity": [10],
            "created_at": [pd.Timestamp("2025-01-01", tz="UTC")],
            # no organization_id column — pre-migration shape
        }
    )
    stale_dir = events_root / "legacy"
    stale_dir.mkdir(parents=True)
    stale_df.to_parquet(stale_dir / "inventory_events_start_999_end_999.parquet", index=False)

    count = build_fact_table()

    # Doesn't crash on the schema mismatch, and the stale row — unable to
    # be attributed to an org — drops out of the join rather than being
    # included un-scoped.
    assert count == 1


def test_balance_query(client, db, warehouse_paths, export_paths):
    # 1. Create product and known events
    product = create_product(client)
    pid = product["id"]

    purchase(client, pid, 50)  # balance → 50
    purchase(client, pid, 30)  # balance → 80

    # SALE is stored as -10 internally
    client.post(
        "/api/inventory/events",
        json={
            "product_id": pid,
            "event_type": "SALE",
            "quantity": 10,
            "event_id": f"evt-sale-{uuid.uuid4()}",
        },
    )  # balance → 70

    # 2. Export and build warehouse
    db.expire_all()
    export_inventory_events(db, incremental=False)

    db.expire_all()
    build_dim_products(db)
    build_fact_table()

    # 3. Run running balance query
    conn = duckdb.connect()
    df = conn.execute(f"""
        SELECT
            product_id,
            quantity,
            SUM(quantity) OVER (
                PARTITION BY product_id
                ORDER BY date_id
            ) AS running_balance
        FROM read_parquet('{warehouse_paths}/fact_inventory_events.parquet')
        ORDER BY product_id, date_id
    """).df()
    conn.close()

    # 4. Assert final balance for our product
    final_balance = df[df["product_id"] == pid].iloc[-1]["running_balance"]
    assert final_balance == 70
