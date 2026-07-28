# app/services/feature_service.py

import duckdb

from app.config import FEATURE_STORE_PATH, WAREHOUSE_DB_PATH
from app.core import storage
from app.core.logging import logger


def _ensure_directories() -> None:
    storage.mkdir(FEATURE_STORE_PATH)


def build_features() -> int:
    # Always local — see app/config.py's WAREHOUSE_DB_PATH and
    # warehouse/ims_warehouse/profiles.yml, which opens this same file.
    conn = duckdb.connect(WAREHOUSE_DB_PATH)

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
    storage.to_parquet(df, storage.join(FEATURE_STORE_PATH, "daily_sales.parquet"))

    logger.info("feature_build_completed", extra={"rows_written": len(df)})

    return len(df)
