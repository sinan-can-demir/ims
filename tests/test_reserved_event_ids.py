# Client-supplied event_ids must not collide with system-derived formats
# (#392): "po-{id}-line-{id}" and "{event}:component:{id}".

import pytest

from app.schemas.event_ids import reject_reserved_event_id
from app.schemas.ingestion import IngestRowInput

from .utils import create_product, signed_webhook_request
from .utils import set_webhook_secret as _set_webhook_secret

_SECRET = "test-webhook-secret"  # noqa: S105 -- test fixture value, not a real credential


@pytest.mark.parametrize("event_id", ["po-12-line-345", "evt-1:component:7", "a:component:b"])
def test_single_event_rejects_reserved_ids(client, event_id):
    product = create_product(client)
    r = client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "PURCHASE",
            "quantity": 5,
            "event_id": event_id,
        },
    )
    assert r.status_code == 422, r.json()
    assert client.get(f"/api/inventory/{product['id']}").json()["quantity"] == 0


@pytest.mark.parametrize(
    "event_id", ["evt-1", "po-12", "po-12-line-x", "my-po-1-line-2", "component"]
)
def test_ordinary_ids_still_accepted(client, event_id):
    product = create_product(client)
    r = client.post(
        "/api/inventory/events",
        json={
            "product_id": product["id"],
            "event_type": "PURCHASE",
            "quantity": 5,
            "event_id": event_id,
        },
    )
    assert r.status_code == 201, r.json()


def test_ingest_row_rejects_reserved_ids():
    for event_id in ("po-1-line-1", "x:component:2"):
        with pytest.raises(ValueError):
            IngestRowInput(sku="s", event_type="PURCHASE", quantity=1, event_id=event_id)


def test_webhook_cannot_forge_component_id(client, db):
    _set_webhook_secret(db, 1, _SECRET)
    product = create_product(client)
    payload = {
        "source": "generic",
        "events": [
            {
                "sku": product["sku"],
                "event_type": "PURCHASE",
                "quantity": 9,
                "external_id": "evt:component:1",
            }
        ],
    }
    r = signed_webhook_request(client, 1, payload, _SECRET)
    body = r.json()
    assert body["rows_succeeded"] == 0, body
    assert client.get(f"/api/inventory/{product['id']}").json()["quantity"] == 0


def test_validator_passes_value_through():
    assert reject_reserved_event_id("ok-id") == "ok-id"
