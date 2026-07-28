# app/services/warehouse_service.py
# NOTE: dim_products and dim_dates builders are kept for bootstrapping.
# fact_inventory_events is now managed by dbt.
# See warehouse/ims_warehouse/ for the dbt project.

from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy.orm import Session

from app.config import INVENTORY_EVENTS_ROOT, WAREHOUSE_ROOT
from app.core.logging import logger
from app.models.product import Product

# app.config exports these as plain strings (so an s3:// URI doesn't get
# mangled by Path), but this file hasn't been migrated to
# app.core.storage yet (see #22) — wrap back to Path here so existing
# local-mode behavior stays exactly as it was.
INVENTORY_EVENTS_ROOT = Path(INVENTORY_EVENTS_ROOT)
WAREHOUSE_ROOT = Path(WAREHOUSE_ROOT)


def _ensure_directories() -> None:
    WAREHOUSE_ROOT.mkdir(parents=True, exist_ok=True)


_UNSAFE_CHARS = frozenset("'\";\\")


def _safe_path(path: Path, root: Path) -> str:
    """Return the absolute string form of path for DuckDB f-string
    interpolation (read_parquet has no bind-param support for the glob
    itself — see docs/archive/report.md M3), after checking it resolves to
    somewhere inside root and contains no unsafe characters. root is never
    attacker-influenced today, but this keeps the guard meaningful once
    paths derive from more than static env config.
    """
    resolved = path.resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"Path {resolved} escapes expected root {resolved_root}")

    resolved_str = str(resolved)
    bad = _UNSAFE_CHARS & set(resolved_str)
    if bad:
        raise ValueError(f"Path contains unsafe characters {bad!r}: {resolved_str}")
    return resolved_str


def build_dim_products(db: Session) -> int:

    # 1. Query all products
    products = db.query(Product).all()

    # 2. Convert to DataFrame
    df = pd.DataFrame(
        [
            {"product_id": p.id, "name": p.name, "sku": p.sku, "created_at": p.created_at}
            for p in products
        ]
    )

    # 3. Ensure warehouse directory exists
    _ensure_directories()

    # 4. Write to parquet
    file_path = WAREHOUSE_ROOT / "dim_products.parquet"
    df.to_parquet(file_path, index=False)

    return len(df)


def build_dim_dates(start_date, end_date) -> int:

    # 1. Get all dates from start_date to end_date
    dates = pd.date_range(start=start_date, end=end_date, freq="D")

    # 2. Build a DataFrame using dates
    df = pd.DataFrame(
        {
            "date_id": dates.strftime("%Y-%m-%d"),
            "year": dates.year,
            "month": dates.month,
            "day": dates.day,
            "quarter": dates.quarter,
            "day_of_week": dates.day_name(),
            "is_weekend": dates.day_name().isin(["Saturday", "Sunday"]),
        }
    )

    # 3. Ensure data warehouse exists
    _ensure_directories()

    # 4. write to parquet
    file_path = WAREHOUSE_ROOT / "dim_dates.parquet"
    df.to_parquet(file_path, index=False)

    # 5. return the row count
    return len(df)


def build_fact_table() -> int:

    # 1. Connect to DuckDB in memory
    conn = duckdb.connect()

    # 2. Ensure directory exists
    _ensure_directories()

    # 3. Read inventory events from data_lake
    # This query has 2 scanning (FROM looks for events AND JOIN looks for products)
    # and one conditional check(ON) for product id. normally makes an O(m X n) complexity.
    # But DuckDB uses a hash join here — O(n + m) where n is events and m is products.
    # Products table is small so the hash table fits in memory entirely,
    # making this effectively O(n) in practice.
    events_path = _safe_path(INVENTORY_EVENTS_ROOT, root=INVENTORY_EVENTS_ROOT)
    products_path = _safe_path(WAREHOUSE_ROOT / "dim_products.parquet", root=WAREHOUSE_ROOT)

    # noqa justification: paths are config-derived (INVENTORY_EVENTS_ROOT /
    # WAREHOUSE_ROOT) and already containment-checked by _safe_path() above —
    # not attacker-controlled input, so this isn't an injectable query despite
    # the f-string shape. DuckDB's read_parquet() also has no bind-parameter
    # form for the file path argument, so parameterizing isn't an option here.
    result = conn.execute(f"""
    SELECT
        e.event_id,
        e.product_id,
        strftime(e.created_at, '%Y-%m-%d') AS date_id,
        e.event_type,
        e.quantity,
        e.created_at
    FROM read_parquet('{events_path}/**/*.parquet') e
    JOIN read_parquet('{products_path}') p
        ON e.product_id = p.product_id
    """).df()  # noqa: S608 -- .df() converts directly to pandas DataFrame

    # 4. write to warehouse/fact_inventory_events.parquet
    file_path = WAREHOUSE_ROOT / "fact_inventory_events.parquet"
    result.to_parquet(file_path, index=False)

    # 5. Close duckdb connection
    conn.close()

    # 6. Return the row count
    return len(result)


def build_warehouse(db: Session, start_date: str, end_date: str) -> None:
    _ensure_directories()

    products_count = build_dim_products(db)
    dates_count = build_dim_dates(start_date, end_date)
    facts_count = build_fact_table()

    logger.info(
        "warehouse_built",
        extra={
            "dim_products_rows": products_count,
            "dim_dates_rows": dates_count,
            "fact_inventory_events_rows": facts_count,
        },
    )
