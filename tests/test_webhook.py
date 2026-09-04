# tests/test_webhook.py

import json
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.auth import require_webhook_signature
from app.models.organization import Organization

from .utils import create_product, signed_webhook_request
from .utils import set_webhook_secret as _set_webhook_secret

_SECRET = "test-webhook-secret"  # noqa: S105 -- test fixture value, not a real credential


def _signed_request(client, organization_id: int, payload: dict, secret: str = _SECRET):
    return signed_webhook_request(client, organization_id, payload, secret)


def _payload(sku, event_type="PURCHASE", quantity=10, external_id=None):
    return {
        "source": "generic",
        "events": [
            {
                "sku": sku,
                "event_type": event_type,
                "quantity": quantity,
                "external_id": external_id or f"txn-{uuid.uuid4()}",
            }
        ],
    }


def test_webhook_valid_signature_creates_event(client, db):
    _set_webhook_secret(db, 1, _SECRET)
    product = create_product(client)
    payload = _payload(product["sku"], quantity=15)

    response = _signed_request(client, 1, payload)

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 0

    inventory = client.get(f"/api/inventory/{product['id']}")
    assert inventory.json()["quantity"] == 15


def test_webhook_missing_signature_returns_401(client, db):
    _set_webhook_secret(db, 1, _SECRET)
    payload = _payload("WGT-001")

    response = client.post("/api/webhooks/1/ingest", json=payload)

    assert response.status_code == 401


def test_webhook_wrong_signature_returns_401(client, db):
    _set_webhook_secret(db, 1, _SECRET)
    payload = _payload("WGT-001")
    body = json.dumps(payload).encode()

    response = client.post(
        "/api/webhooks/1/ingest",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": "wrong-signature"},
    )

    assert response.status_code == 401


async def test_require_webhook_signature_rejects_null_secret():
    """
    webhook_secret is NOT NULL at the schema level, so this state can't
    be reached through the running app or even a raw SQL UPDATE — but
    require_webhook_signature() must still fail closed (401) if it's
    ever called against an org whose secret is unset, rather than
    silently treating that as "verification disabled" (the behavior
    this whole fix replaces). Exercises the function directly with a
    mocked db/Organization since the real schema can't produce this row.
    """
    fake_org = Organization(id=1, name="Fake Org", webhook_secret=None)
    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = fake_org

    fake_request = MagicMock()
    fake_request.headers.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await require_webhook_signature(organization_id=1, request=fake_request, db=fake_db)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or missing webhook signature"


def test_webhook_event_id_namespaced_by_source(client, db):
    _set_webhook_secret(db, 1, _SECRET)
    product = create_product(client)
    external_id = f"txn-{uuid.uuid4()}"
    payload = _payload(product["sku"], quantity=5, external_id=external_id)

    response = _signed_request(client, 1, payload)

    assert response.status_code == 200

    from app.models.inventory_event import InventoryEvent

    event = (
        db.query(InventoryEvent).filter(InventoryEvent.event_id == f"generic:{external_id}").first()
    )
    assert event is not None
    # No human actor for a webhook-sourced event — NULL, not the caller's
    # own account, since nothing in the webhook payload identifies a user.
    assert event.created_by_id is None


def test_webhook_too_many_events_returns_422(client, db):
    """
    events has a max_length=1000 (app/schemas/webhook.py) — a single call
    is still bounded by this schema validation regardless of the route's
    own per-org rate limit (enforce_webhook_rate_limit), which caps
    request *count*, not payload size per request.
    """
    _set_webhook_secret(db, 1, _SECRET)
    payload = {
        "source": "generic",
        "events": [
            {
                "sku": "does-not-matter",
                "event_type": "PURCHASE",
                "quantity": 1,
                "external_id": f"txn-{i}",
            }
            for i in range(1001)
        ],
    }

    response = _signed_request(client, 1, payload)

    assert response.status_code == 422


def test_webhook_partial_failure_reported_per_row(client, db):
    _set_webhook_secret(db, 1, _SECRET)
    product = create_product(client)
    payload = {
        "source": "generic",
        "events": [
            {
                "sku": product["sku"],
                "event_type": "PURCHASE",
                "quantity": 10,
                "external_id": f"txn-{uuid.uuid4()}",
            },
            {
                "sku": "unknown-sku",
                "event_type": "PURCHASE",
                "quantity": 10,
                "external_id": f"txn-{uuid.uuid4()}",
            },
        ],
    }

    response = _signed_request(client, 1, payload)

    assert response.status_code == 200
    body = response.json()
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 1


def test_webhook_unknown_organization_returns_404(client, db):
    payload = _payload("WGT-001")

    response = client.post("/api/webhooks/999999/ingest", json=payload)

    assert response.status_code == 404
