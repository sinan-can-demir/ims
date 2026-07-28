# app/services/feature_service.py

from pathlib import Path

import duckdb

from app.config import FEATURE_STORE_PATH, WAREHOUSE_ROOT
from app.core.logging import logger

# app.config exports these as plain strings (so an s3:// URI doesn't get
# mangled by Path), but this file hasn't been migrated to
# app.core.storage yet (see #22) — wrap back to Path here so existing
# local-mode behavior stays exactly as it was.
FEATURE_STORE_PATH = Path(FEATURE_STORE_PATH)
WAREHOUSE_ROOT = Path(WAREHOUSE_ROOT)


def _ensure_directories() -> None:
    FEATURE_STORE_PATH.mkdir(parents=True, exist_ok=True)


def build_features() -> int:
    conn = duckdb.connect(str(WAREHOUSE_ROOT / "ims.duckdb"))

    logger.info("feature_build_started")

    # Step 1 — Read fact table and aggregate by product + day
    # DuckDB handles the SQL, pandas handles the rolling math
    df = conn.execute("""
        SELECT
            product_id,
            date_id AS date,
            SUM(CASE WHEN event_type IN ('SALE', 'DAMAGE', 'WASTE')
                THEN ABS(quantity) ELSE 0 END) AS units_sold,
            SUM(CASE WHEN event_type IN ('PURCHASE', 'RETURN') 
                THEN quantity ELSE 0 END)        AS units_purchased,
            SUM(quantity)                        AS net_delta
        FROM fact_inventory_events
        GROUP BY product_id, date_id
        ORDER BY product_id, date_id
    """).df()

    conn.close()

    # Step 2 — Rolling average using pandas, per product
    # sort_values ensures dates are in order before rolling
    df = df.sort_values(["product_id", "date"])

    df["rolling_avg_7d"] = df.groupby("product_id")["units_sold"].transform(
        lambda x: x.rolling(7, min_periods=1).mean()
    )

    # Step 3 — Write to feature store
    _ensure_directories()
    df.to_parquet(FEATURE_STORE_PATH / "daily_sales.parquet", index=False)

    logger.info("feature_build_completed", extra={"rows_written": len(df)})

    return len(df)
