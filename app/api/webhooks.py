# app/api/webhooks.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_webhook_signature
from app.core.rate_limit import enforce_webhook_ip_rate_limit, enforce_webhook_rate_limit
from app.database import get_db
from app.schemas.ingestion import IngestResponse
from app.schemas.webhook import WebhookIngestPayload
from app.services.ingestion_service import ingest_events

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/{organization_id}/ingest",
    response_model=IngestResponse,
    # Order matters (#386); FastAPI runs these in list order and stops at
    # the first one that raises:
    #   1. per-IP ceiling  - cheap flood rejection before any HMAC/DB work
    #   2. signature check - unsigned/forged requests get 401 here
    #   3. per-org limit   - charged ONLY by verified requests, so an
    #      attacker without the secret can't burn a victim org's bucket
    #      (the org id in the URL is attacker-chosen).
    dependencies=[
        Depends(enforce_webhook_ip_rate_limit),
        Depends(require_webhook_signature),
        Depends(enforce_webhook_rate_limit),
    ],
)
def webhook_ingest(
    organization_id: int, payload: WebhookIngestPayload, db: Session = Depends(get_db)
):
    """
    Generic, platform-agnostic webhook receiver for inventory events —
    signed with the target org's own webhook_secret (X-Webhook-Signature
    header, see require_webhook_signature), not the bearer token used by
    /api routes; a future POS/e-commerce-specific adapter would translate
    its own webhook format into this payload shape. event_id is derived
    as "{source}:{external_id}" so the same external_id from two
    different sources can't collide.
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
    return ingest_events(db, rows, organization_id=organization_id)
