import pandas as pd
from sqlalchemy.orm import Session

from app.config import INVENTORY_EVENTS_ROOT
from app.core import storage
from app.database import SessionLocal
from app.models.inventory_event import InventoryEvent


def validate_exports(db: Session) -> dict:
    parquet_files = storage.glob(INVENTORY_EVENTS_ROOT, "*.parquet")

    db_count = db.query(InventoryEvent).count()

    if not parquet_files:
        return {
            "db_rows": db_count,
            "parquet_rows": 0,
            "duplicate_event_ids": 0,
            "schema_valid": True,
        }

    frames = [storage.read_parquet(path) for path in parquet_files]
    df = pd.concat(frames, ignore_index=True)

    duplicate_event_ids = int(df["event_id"].duplicated().sum())

    expected_columns = {
        "id",
        "event_id",
        "product_id",
        "event_type",
        "quantity",
        "created_at",
        "organization_id",
    }

    schema_valid = set(df.columns) == expected_columns

    return {
        "db_rows": db_count,
        "parquet_rows": int(len(df)),
        "row_count_match": db_count == len(df),
        "duplicate_event_ids": duplicate_event_ids,
        "schema_valid": schema_valid,
    }


def main() -> None:
    db = SessionLocal()
    try:
        result = validate_exports(db)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
