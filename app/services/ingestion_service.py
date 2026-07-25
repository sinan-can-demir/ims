# app/services/ingestion_service.py
#
# Shared core for both the CSV bulk-import endpoint and the webhook
# receiver. Resolves each row's product by SKU, then calls the existing
# record_event() — already idempotent and race-safe via its event_id
# unique-constraint pre-check + IntegrityError fallback, so no new
# idempotency mechanism is needed here. Unlike export_service/replay_service
# (single-commit, all-or-nothing), this collects per-row results so one bad
# row doesn't fail the whole batch.

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.core.logging import logger
from app.schemas.ingestion import IngestRowInput
from app.services.inventory_service import record_event
from app.services.product_service import get_product_by_sku


def ingest_events(db: Session, rows: list[dict], created_by_id: int | None = None) -> dict:
    """
    rows: raw dicts, each expected to have sku/event_type/quantity/event_id
    (validated per-row via IngestRowInput before touching the DB).

    created_by_id: the authenticated user driving this batch, or None for
    the webhook receiver (no human actor) — same attribution rule as
    record_event(), just applied uniformly across the whole batch.
    """
    results = []
    succeeded = 0
    failed = 0

    for row_number, raw_row in enumerate(rows, start=1):
        event_id = raw_row.get("event_id") if isinstance(raw_row, dict) else None

        try:
            row = IngestRowInput(**raw_row)
            event_id = row.event_id

            product = get_product_by_sku(db, row.sku)
            record_event(db, product.id, row.event_type, row.quantity, row.event_id, created_by_id)

            results.append(
                {"row_number": row_number, "event_id": event_id, "status": "success", "error": None}
            )
            succeeded += 1

        except (ValidationError, DomainError) as e:
            db.rollback()
            error_message = str(e) if isinstance(e, DomainError) else _format_validation_error(e)
            results.append(
                {
                    "row_number": row_number,
                    "event_id": event_id,
                    "status": "failed",
                    "error": error_message,
                }
            )
            failed += 1

    logger.info(
        "bulk_ingestion_completed",
        extra={"rows_processed": len(rows), "rows_succeeded": succeeded, "rows_failed": failed},
    )

    return {
        "rows_processed": len(rows),
        "rows_succeeded": succeeded,
        "rows_failed": failed,
        "results": results,
    }


def _format_validation_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = ".".join(str(loc) for loc in first["loc"])
    return f"{field}: {first['msg']}"
