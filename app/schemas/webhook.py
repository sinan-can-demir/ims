from pydantic import BaseModel, Field

# event_type and quantity are kept loose (not EventType/validated int) at
# this outer-payload level on purpose — strict per-row validation happens
# inside ingestion_service.ingest_events (via IngestRowInput), so one
# malformed event in a batch is reported as a per-row failure alongside
# the rest, instead of failing Pydantic validation for the whole payload.


class WebhookEventItem(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    event_type: str
    quantity: int
    external_id: str = Field(min_length=1, max_length=100)


class WebhookIngestPayload(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    # Webhooks are near-real-time deltas, not bulk history dumps (that's
    # POST /api/inventory/events/bulk's job) — 1000 is generous for that
    # use case while still bounding the per-row-DB-round-trip processing
    # cost in ingestion_service.ingest_events(), and this route is
    # explicitly rate-limit-exempt (SECURITY.md) so there's no secondary
    # throttle to lean on.
    events: list[WebhookEventItem] = Field(max_length=1000)
