# app/api/webhooks.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_webhook_signature
from app.database import get_db
from app.schemas.ingestion import IngestResponse
from app.schemas.webhook import WebhookIngestPayload
from app.services.ingestion_service import ingest_events

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    dependencies=[Depends(require_webhook_signature)],
)
def webhook_ingest(payload: WebhookIngestPayload, db: Session = Depends(get_db)):
    """
    Generic, platform-agnostic webhook receiver for inventory events —
    signed with WEBHOOK_SECRET (X-Webhook-Signature header), not the
    X-API-Key used by /api routes; a future POS/e-commerce-specific
    adapter would translate its own webhook format into this payload
    shape. event_id is derived as "{source}:{external_id}" so the same
    external_id from two different sources can't collide.
    """
    rows = [
        {
            "sku": event.sku,
            "event_type": event.event_type,
            "quantity": event.quantity,
            "event_id": f"{payload.source}:{event.external_id}",
        }
        for event in payload.events
    ]
    return ingest_events(db, rows)
