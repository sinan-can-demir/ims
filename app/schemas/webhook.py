from pydantic import BaseModel, Field

# event_type and quantity are kept loose (not EventType/validated int) at
# this outer-payload level on purpose — strict per-row validation happens
# inside ingestion_service.ingest_events (via IngestRowInput), so one
# malformed event in a batch is reported as a per-row failure alongside
# the rest, instead of failing Pydantic validation for the whole payload.


# Named (and imported by schemas/ingestion.py) because the webhook receiver
# builds event_id as "{source}:{external_id}", so IngestRowInput's event_id cap
# must be derived from these two, not hard-coded separately.
WEBHOOK_SOURCE_MAX_LENGTH = 50
WEBHOOK_EXTERNAL_ID_MAX_LENGTH = 100


class WebhookEventItem(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    event_type: str
    quantity: int
    external_id: str = Field(min_length=1, max_length=WEBHOOK_EXTERNAL_ID_MAX_LENGTH)


class WebhookIngestPayload(BaseModel):
    source: str = Field(min_length=1, max_length=WEBHOOK_SOURCE_MAX_LENGTH)
    # Webhooks are near-real-time deltas, not bulk history dumps (that's
    # POST /api/inventory/events/bulk's job) — 1000 is generous for that
    # use case while still bounding the per-row-DB-round-trip processing
    # cost in ingestion_service.ingest_events(), and this route is
    # rate-limited per org and per IP (SECURITY.md), but those limit request
    # count, not events per request, so this cap is what bounds one
    # request's work.
    events: list[WebhookEventItem] = Field(max_length=1000)
