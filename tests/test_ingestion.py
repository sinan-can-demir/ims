# tests/test_ingestion.py

import io
import uuid

from app.models.inventory_event import InventoryEvent
from app.models.user import User
from app.services.ingestion_service import ingest_events

from .utils import create_product


def _row(sku, event_type="PURCHASE", quantity=10, event_id=None):
    return {
        "sku": sku,
        "event_type": event_type,
        "quantity": quantity,
        "event_id": event_id or f"evt-{uuid.uuid4()}",
    }


# ---------------------------------------------------------------
# ingestion_service.ingest_events — unit tests
# ---------------------------------------------------------------


def test_ingest_events_mixed_success_and_failure(client, db):
    product = create_product(client)

    rows = [
        _row(product["sku"], quantity=10),
        _row("nonexistent-sku", quantity=5),
    ]

    result = ingest_events(db, rows)

    assert result["rows_processed"] == 2
    assert result["rows_succeeded"] == 1
    assert result["rows_failed"] == 1
    assert result["results"][0]["status"] == "success"
    assert result["results"][1]["status"] == "failed"
    assert "nonexistent-sku" in result["results"][1]["error"]


def test_ingest_events_unit_price_flows_through_to_the_stored_event(client, db):
    """
    ROADMAP.md's "Food Cost Visibility" Phase 3 -- this is the exact core
    a POS connector will call (translate external sale data into this
    generic row shape, then ingest_events()). Confirms unit_price isn't
    silently dropped anywhere between the row dict and the persisted
    InventoryEvent.
    """
    product = create_product(client)
    row = _row(product["sku"], event_type="PURCHASE", quantity=2)
    row["unit_price"] = 14.50

    result = ingest_events(db, [row])
    assert result["rows_succeeded"] == 1

    event = db.query(InventoryEvent).filter(InventoryEvent.event_id == row["event_id"]).first()
    assert event is not None
    assert float(event.unit_price) == 14.50


def test_ingest_events_duplicate_event_id_is_idempotent(client, db):
    product = create_product(client)
    shared_event_id = f"evt-{uuid.uuid4()}"

    rows = [
        _row(product["sku"], quantity=10, event_id=shared_event_id),
        _row(product["sku"], quantity=10, event_id=shared_event_id),
    ]

    result = ingest_events(db, rows)

    assert result["rows_succeeded"] == 2
    assert result["rows_failed"] == 0


def test_ingest_events_unknown_sku_is_a_row_failure_not_a_crash(db):
    rows = [_row("does-not-exist")]

    result = ingest_events(db, rows)

    assert result["rows_processed"] == 1
    assert result["rows_failed"] == 1
    assert result["results"][0]["status"] == "failed"


def test_ingest_events_missing_required_field_is_a_row_failure(client, db):
    product = create_product(client)

    rows = [{"sku": product["sku"], "event_type": "PURCHASE"}]  # missing quantity, event_id

    result = ingest_events(db, rows)

    assert result["rows_failed"] == 1
    assert result["results"][0]["status"] == "failed"


def test_ingest_events_invalid_event_type_is_a_row_failure(client, db):
    product = create_product(client)

    rows = [_row(product["sku"], event_type="NOT_A_REAL_TYPE")]

    result = ingest_events(db, rows)

    assert result["rows_failed"] == 1


def test_ingest_events_oversell_is_a_row_failure(client, db):
    product = create_product(client)

    rows = [_row(product["sku"], event_type="SALE", quantity=10)]

    result = ingest_events(db, rows)

    assert result["rows_failed"] == 1
    assert result["results"][0]["status"] == "failed"


def test_ingest_events_records_created_by_id(client, db):
    current_user = db.query(User).filter(User.email == "test-client@example.com").first()
    product = create_product(client)

    result = ingest_events(db, [_row(product["sku"], quantity=10)], created_by_id=current_user.id)

    assert result["rows_succeeded"] == 1
    event = db.query(InventoryEvent).order_by(InventoryEvent.id.desc()).first()
    assert event.created_by_id == current_user.id


def test_ingest_events_defaults_created_by_id_to_none(client, db):
    """Matches the webhook receiver, which never passes created_by_id."""
    product = create_product(client)

    ingest_events(db, [_row(product["sku"], quantity=10)])

    event = db.query(InventoryEvent).order_by(InventoryEvent.id.desc()).first()
    assert event.created_by_id is None


# ---------------------------------------------------------------
# POST /api/inventory/events/bulk — integration tests
# ---------------------------------------------------------------


def test_bulk_import_endpoint_csv_upload(client):
    product = create_product(client)
    event_id = f"evt-{uuid.uuid4()}"

    csv_content = f"sku,event_type,quantity,event_id\n{product['sku']},PURCHASE,25,{event_id}\n"
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["rows_processed"] == 1
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 0

    inventory = client.get(f"/api/inventory/{product['id']}")
    assert inventory.json()["quantity"] == 25


def test_bulk_import_endpoint_records_created_by_id(client, db):
    current_user = db.query(User).filter(User.email == "test-client@example.com").first()
    product = create_product(client)
    event_id = f"evt-{uuid.uuid4()}"

    csv_content = f"sku,event_type,quantity,event_id\n{product['sku']},PURCHASE,25,{event_id}\n"
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)
    assert response.status_code == 200, response.json()

    events = client.get(f"/api/inventory/events/{product['id']}").json()
    assert events[0]["created_by_id"] == current_user.id


def test_bulk_import_endpoint_missing_columns_returns_400(client):
    csv_content = "sku,quantity\nWGT-001,5\n"
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)

    assert response.status_code == 400


def test_bulk_import_endpoint_oversized_file_returns_413(client):
    from app.api.inventory import _BULK_IMPORT_MAX_BYTES

    oversized = b"x" * (_BULK_IMPORT_MAX_BYTES + 1)
    files = {"file": ("events.csv", io.BytesIO(oversized), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)

    assert response.status_code == 413


def test_bulk_import_endpoint_too_many_rows_returns_413(client):
    from app.api.inventory import _BULK_IMPORT_MAX_ROWS

    header = "sku,event_type,quantity,event_id\n"
    row_count = _BULK_IMPORT_MAX_ROWS + 1
    rows = "".join(f"sku-{i},PURCHASE,1,evt-{i}\n" for i in range(row_count))
    csv_content = header + rows
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)

    assert response.status_code == 413


def test_bulk_import_endpoint_partial_failure(client):
    product = create_product(client)
    event_id = f"evt-{uuid.uuid4()}"

    csv_content = (
        "sku,event_type,quantity,event_id\n"
        f"{product['sku']},PURCHASE,10,{event_id}\n"
        f"unknown-sku,PURCHASE,10,evt-{uuid.uuid4()}\n"
    )
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode()), "text/csv")}

    response = client.post("/api/inventory/events/bulk", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["rows_succeeded"] == 1
    assert body["rows_failed"] == 1
