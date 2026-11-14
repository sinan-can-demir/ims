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
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.core.logging import logger
from app.schemas.ingestion import IngestRowInput
from app.services.inventory_service import record_event
from app.services.product_service import get_product_by_sku

# Postgres SQLSTATEs that mean "this transaction lost a race, try again":
# deadlock_detected and serialization_failure. Anything else is not retried.
_RETRYABLE_SQLSTATES = {"40P01", "40001"}

# Deliberately generic: raw driver text can include SQL and parameters.
_DB_ERROR_MESSAGE = "temporary database error, retry this row"


def _is_retryable_db_error(exc: SQLAlchemyError) -> bool:
    if not isinstance(exc, DBAPIError):
        return False
    orig = exc.orig
    # psycopg2 exposes pgcode, psycopg v3 exposes sqlstate.
    code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    return code in _RETRYABLE_SQLSTATES


def _record_row(db, row, product_id, created_by_id, organization_id):
    record_event(
        db,
        product_id,
        row.event_type,
        row.quantity,
        row.event_id,
        created_by_id,
        organization_id,
        row.unit_price,
    )


def ingest_events(
    db: Session,
    rows: list[dict],
    created_by_id: int | None = None,
    organization_id: int = 1,
) -> dict:
    """
    rows: raw dicts, each expected to have sku/event_type/quantity/event_id
    (validated per-row via IngestRowInput before touching the DB).

    created_by_id: the authenticated user driving this batch, or None for
    the webhook receiver (no human actor) — same attribution rule as
    record_event(), just applied uniformly across the whole batch.

    organization_id: defaults to 1 only for callers that don't pass it
    explicitly (e.g. direct test/script use) — both real call sites
    (the CSV bulk-import route and, as of Epoch 10 PR 12/#148, the
    webhook receiver's resolved {organization_id} path param) already
    pass it explicitly.
    """
    results = []
    succeeded = 0
    failed = 0

    for row_number, raw_row in enumerate(rows, start=1):
        event_id = raw_row.get("event_id") if isinstance(raw_row, dict) else None

        try:
            row = IngestRowInput(**raw_row)
            event_id = row.event_id

            product = get_product_by_sku(db, row.sku, organization_id)
            try:
                _record_row(db, row, product.id, created_by_id, organization_id)
            except SQLAlchemyError as e:
                # record_event already rolled back. A deadlock/serialization
                # failure is transient, so retry once; the event_id check
                # makes the retry idempotent. Other DB errors fall through
                # to the per-row failure handler below.
                if not _is_retryable_db_error(e):
                    raise
                logger.warning("ingest_row_retry", extra={"event_id": event_id})
                db.rollback()
                _record_row(db, row, product.id, created_by_id, organization_id)

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

        except SQLAlchemyError:
            # Unexpected/persistent DB error (incl. a retry that failed
            # again). Without this the whole request 500s after earlier rows
            # already committed and the caller loses every per-row result.
            db.rollback()
            logger.exception("ingest_row_db_error", extra={"event_id": event_id})
            results.append(
                {
                    "row_number": row_number,
                    "event_id": event_id,
                    "status": "failed",
                    "error": _DB_ERROR_MESSAGE,
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
