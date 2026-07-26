# tests/test_webhook.py

import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

from .utils import create_product

_SECRET = "test-webhook-secret"  # noqa: S105 -- test fixture value, not a real credential


def _signed_request(client, payload: dict, secret: str = _SECRET):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/webhooks/ingest",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )


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


def test_webhook_valid_signature_creates_event(client):
    product = create_product(client)
    payload = _payload(product["sku"], quantity=15)

    with patch("app.core.auth._WEBHOOK_SECRET", _SECRET):
        response = _signed_request(client, payload)

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 0

    inventory = client.get(f"/api/inventory/{product['id']}")
    assert inventory.json()["quantity"] == 15


def test_webhook_missing_signature_returns_401(client):
    payload = _payload("WGT-001")

    with patch("app.core.auth._WEBHOOK_SECRET", _SECRET):
        response = client.post("/api/webhooks/ingest", json=payload)

    assert response.status_code == 401


def test_webhook_wrong_signature_returns_401(client):
    payload = _payload("WGT-001")
    body = json.dumps(payload).encode()

    with patch("app.core.auth._WEBHOOK_SECRET", _SECRET):
        response = client.post(
            "/api/webhooks/ingest",
            content=body,
            headers={"Content-Type": "application/json", "X-Webhook-Signature": "wrong-signature"},
        )

    assert response.status_code == 401


def test_webhook_no_secret_configured_allows_unsigned_requests(client):
    product = create_product(client)
    payload = _payload(product["sku"])

    with patch("app.core.auth._WEBHOOK_SECRET", None):
        response = client.post("/api/webhooks/ingest", json=payload)

    assert response.status_code == 200


def test_webhook_event_id_namespaced_by_source(client, db):
    product = create_product(client)
    external_id = f"txn-{uuid.uuid4()}"
    payload = _payload(product["sku"], quantity=5, external_id=external_id)

    with patch("app.core.auth._WEBHOOK_SECRET", _SECRET):
        response = _signed_request(client, payload)

    assert response.status_code == 200

    from app.models.inventory_event import InventoryEvent

    event = (
        db.query(InventoryEvent).filter(InventoryEvent.event_id == f"generic:{external_id}").first()
    )
    assert event is not None
    # No human actor for a webhook-sourced event — NULL, not the caller's
    # own account, since nothing in the webhook payload identifies a user.
    assert event.created_by_id is None


def test_webhook_too_many_events_returns_422(client):
    """
    events has a max_length=1000 (app/schemas/webhook.py) — this route is
    explicitly rate-limit-exempt, so schema validation is the only thing
    bounding how much a single call can force ingest_events() to process.
    """
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

    with patch("app.core.auth._WEBHOOK_SECRET", _SECRET):
        response = _signed_request(client, payload)

    assert response.status_code == 422


def test_webhook_partial_failure_reported_per_row(client):
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

    with patch("app.core.auth._WEBHOOK_SECRET", _SECRET):
        response = _signed_request(client, payload)

    assert response.status_code == 200
    body = response.json()
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 1
