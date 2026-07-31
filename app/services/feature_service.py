# app/services/feature_service.py

import duckdb

from app.config import FEATURE_STORE_PATH, WAREHOUSE_DB_PATH
from app.core import storage
from app.core.logging import logger


def _ensure_directories(organization_id: int) -> None:
    storage.mkdir(storage.join(FEATURE_STORE_PATH, f"org_id={organization_id}"))


def build_features(organization_id: int = 1) -> int:
    """
    org_id={organization_id} is a real directory level in the output path
    (Epoch 10 PR 15, #151), not just a WHERE filter — this also directly
    fixes the pre-existing "rebuilds the entire table every run"
    operability problem: before this, every call overwrote one single
    global daily_sales.parquet covering every product across the whole
    deployment, regardless of which org actually needed a refresh. Now
    each org has its own file, so building one org's features only
    touches that org's output.
    """
    # Always local — see app/config.py's WAREHOUSE_DB_PATH and
    # warehouse/ims_warehouse/profiles.yml, which opens this same file.
    conn = duckdb.connect(WAREHOUSE_DB_PATH)

    logger.info("feature_build_started", extra={"organization_id": organization_id})

    # Step 1 — Read fact table and aggregate by product + day, scoped to
    # this org. DuckDB handles the SQL, pandas handles the rolling math.
    df = conn.execute(
        """
        SELECT
            product_id,
            date_id AS date,
            SUM(CASE WHEN event_type IN ('SALE', 'DAMAGE', 'WASTE')
                THEN ABS(quantity) ELSE 0 END) AS units_sold,
            SUM(CASE WHEN event_type IN ('PURCHASE', 'RETURN')
                THEN quantity ELSE 0 END)        AS units_purchased,
            SUM(quantity)                        AS net_delta
        FROM fact_inventory_events
        WHERE organization_id = ?
        GROUP BY product_id, date_id
        ORDER BY product_id, date_id
        """,
        [organization_id],
    ).df()

    conn.close()

    # Step 2 — Rolling average using pandas, per product
    # sort_values ensures dates are in order before rolling
    df = df.sort_values(["product_id", "date"])

    df["rolling_avg_7d"] = df.groupby("product_id")["units_sold"].transform(
        lambda x: x.rolling(7, min_periods=1).mean()
    )

    # Step 3 — Write to feature store
    _ensure_directories(organization_id)
    storage.to_parquet(
        df, storage.join(FEATURE_STORE_PATH, f"org_id={organization_id}", "daily_sales.parquet")
    )

    logger.info(
        "feature_build_completed",
        extra={"rows_written": len(df), "organization_id": organization_id},
    )

    return len(df)
