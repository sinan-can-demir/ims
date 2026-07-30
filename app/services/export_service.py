from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.config import CHECKPOINT_FILE, INVENTORY_EVENTS_ROOT
from app.core import storage
from app.core.logging import logger
from app.models.inventory_event import InventoryEvent

CHECKPOINT_KEY = "inventory_events"


def _ensure_directories() -> None:
    # A single mkdir suffices — CHECKPOINT_FILE always lives directly under
    # DATA_LAKE_ROOT (app/config.py), which INVENTORY_EVENTS_ROOT is nested
    # one level under, so creating the latter (with parents) also creates
    # the former's parent. No-op entirely under S3 (see app/core/storage.py).
    storage.mkdir(INVENTORY_EVENTS_ROOT)


def _load_checkpoints() -> dict[str, Any]:
    _ensure_directories()

    if not storage.exists(CHECKPOINT_FILE):
        return {}

    with storage.open_read(CHECKPOINT_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_checkpoints(checkpoints: dict[str, Any]) -> None:
    _ensure_directories()

    with storage.open_write(CHECKPOINT_FILE, encoding="utf-8") as f:
        json.dump(checkpoints, f, indent=2)


def _get_checkpoint() -> dict[str, Any] | None:
    checkpoints = _load_checkpoints()
    return checkpoints.get(CHECKPOINT_KEY)


def _update_checkpoint(last_id: int) -> None:
    checkpoints = _load_checkpoints()
    checkpoints[CHECKPOINT_KEY] = {
        "last_id": last_id,
    }
    _save_checkpoints(checkpoints)


def _build_base_query(db: Session):
    """
    Deliberately not organization_id-filtered — this stays a single,
    whole-deployment export spanning every org in one run (Epoch 10 PR 13,
    #149), same as the checkpoint below staying global. organization_id
    is still selected as a real column so the write step can partition by
    it; see _write_partitioned_parquet().
    """
    return db.query(
        InventoryEvent.id,
        InventoryEvent.event_id,
        InventoryEvent.product_id,
        InventoryEvent.event_type,
        InventoryEvent.quantity,
        InventoryEvent.created_at,
        InventoryEvent.organization_id,
    ).order_by(InventoryEvent.created_at.asc(), InventoryEvent.id.asc())


def _apply_incremental_filter(query, checkpoint: dict | None):
    if not checkpoint:
        return query

    last_id = checkpoint["last_id"]
    return query.filter(InventoryEvent.id > last_id)


def _rows_to_dataframe(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(
        rows,
        columns=[
            "id",
            "event_id",
            "product_id",
            "event_type",
            "quantity",
            "created_at",
            "organization_id",
        ],
    )

    if df.empty:
        return df

    df["event_type"] = df["event_type"].astype(str)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)

    df["year"] = df["created_at"].dt.strftime("%Y")
    df["month"] = df["created_at"].dt.strftime("%m")
    df["day"] = df["created_at"].dt.strftime("%d")

    return df


def _write_partitioned_parquet(df: pd.DataFrame) -> tuple[int, int]:
    """
    org_id= is the outermost partition level, ahead of year/month/day
    (Epoch 10 PR 13, #149) — e.g.
    INVENTORY_EVENTS_ROOT/org_id=5/year=2026/month=07/day=28/... — and,
    unlike year/month/day (partition-path-only, never written into the
    file itself), organization_id is also kept as a real column in each
    written parquet file, since downstream consumers (warehouse build,
    dbt) read it directly rather than parsing it back out of the path.
    """
    if df.empty:
        return 0, 0

    partitions_written = 0
    files_written = 0

    grouped = df.groupby(["organization_id", "year", "month", "day"], sort=True)

    for (org_id, year, month, day), partition_df in grouped:
        partition_path = storage.join(
            INVENTORY_EVENTS_ROOT,
            f"org_id={org_id}",
            f"year={year}",
            f"month={month}",
            f"day={day}",
        )
        storage.mkdir(partition_path)

        start_id = int(partition_df["id"].min())
        end_id = int(partition_df["id"].max())

        file_path = storage.join(
            partition_path, f"inventory_events_start_{start_id}_end_{end_id}.parquet"
        )

        write_df = (
            partition_df[
                [
                    "id",
                    "event_id",
                    "product_id",
                    "event_type",
                    "quantity",
                    "created_at",
                    "organization_id",
                ]
            ]
            .sort_values(["created_at", "id"])
            .reset_index(drop=True)
        )

        storage.to_parquet(write_df, file_path)

        partitions_written += 1
        files_written += 1

    return partitions_written, files_written


def export_inventory_events(db: Session, incremental: bool = True) -> dict[str, Any]:
    logger.info("inventory_export_started")

    checkpoint = _get_checkpoint() if incremental else None

    query = _build_base_query(db)
    query = _apply_incremental_filter(query, checkpoint)
    rows = query.all()

    df = _rows_to_dataframe(rows)

    if df.empty:
        logger.info("inventory_export_empty")
        return {
            "rows_exported": 0,
            "partitions_written": 0,
            "files_written": 0,
            "mode": "incremental" if incremental else "full",
            "checkpoint_updated": False,
        }

    try:
        partitions_written, files_written = _write_partitioned_parquet(df)

        last_row = df.sort_values(["created_at", "id"]).iloc[-1]
        _update_checkpoint(last_id=int(last_row["id"]))
    except Exception:
        logger.exception("inventory_export_failed")
        raise

    return {
        "rows_exported": int(len(df)),
        "partitions_written": partitions_written,
        "files_written": files_written,
        "mode": "incremental" if incremental else "full",
        "checkpoint_updated": True,
    }
