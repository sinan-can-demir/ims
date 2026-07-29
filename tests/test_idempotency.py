import threading

import pytest

from app.models.enums import EventType
from app.models.inventory_event import InventoryEvent
from app.models.inventory_state import InventoryState
from app.models.product import Product
from app.services.inventory_service import record_event

from .conftest import TestingSessionLocal
from .utils import create_product


def test_idempotent_event(client):

    product = create_product(client)
    product_id = product["id"]

    payload = {
        "product_id": product_id,
        "event_type": "PURCHASE",
        "quantity": 50,
        "event_id": "same-event",
    }

    # First request
    r1 = client.post("/api/inventory/events", json=payload)
    assert r1.status_code == 201

    # Duplicate request — same event_id, must return 201 without double-counting
    r2 = client.post("/api/inventory/events", json=payload)
    assert r2.status_code == 201

    # Inventory should still be 50 (not 100)
    response = client.get(f"/api/inventory/{product_id}")

    assert response.json()["quantity"] == 50


def test_same_event_id_different_orgs_both_succeed(client, client_org2, db, second_org):
    """
    Epoch 10 PR 6 (see migrations/versions/ffdda217be31): event_id
    uniqueness is now UNIQUE(organization_id, event_id), not global — two
    orgs recording the literal same event_id string must not collide.

    org2_product is built directly via the ORM, not via
    create_product(client_org2) — product_service.create_product() isn't
    org-threaded until a later Epoch 10 PR (#143), so every product
    created through the API lands in org 1 regardless of which org's
    client makes the request; a real org-2 product doesn't exist through
    the API yet.
    """
    org1_product = create_product(client)

    org2_product = Product(organization_id=second_org.id, name="Org2 Widget", sku="org2-widget")
    db.add(org2_product)
    db.commit()
    db.refresh(org2_product)

    payload_shape = {
        "event_type": "PURCHASE",
        "quantity": 30,
        "event_id": "shared-literal-event-id",
    }

    r1 = client.post(
        "/api/inventory/events", json={**payload_shape, "product_id": org1_product["id"]}
    )
    assert r1.status_code == 201

    r2 = client_org2.post(
        "/api/inventory/events", json={**payload_shape, "product_id": org2_product.id}
    )
    assert r2.status_code == 201

    assert client.get(f"/api/inventory/{org1_product['id']}").json()["quantity"] == 30
    assert client_org2.get(f"/api/inventory/{org2_product.id}").json()["quantity"] == 30


@pytest.mark.postgres
def test_concurrent_duplicate_event_same_org_applies_once(db):
    """
    Real load/concurrency coverage for the idempotency-critical
    with_for_update() row lock (flagged HIGH RISK, see issue #142) — not
    just a sequential correctness check. N threads race to record the
    exact same event_id against the same product in the same org, each
    on its own real DB connection (a fresh TestingSessionLocal() per
    thread, not the shared `db` fixture session — a single SQLAlchemy
    Session isn't safe for concurrent use and wouldn't exercise real
    connection-level row locking). Exactly one must win; the rest must
    dedupe via the org-scoped unique constraint +
    record_event()'s IntegrityError-catch-and-retry path, not silently
    double-apply.
    """
    product = Product(organization_id=1, name="Concurrency Widget", sku="concurrency-widget")
    db.add(product)
    db.commit()
    db.refresh(product)
    product_id = product.id

    thread_count = 8
    barrier = threading.Barrier(thread_count)
    results = [None] * thread_count

    def _worker(i):
        session = TestingSessionLocal()
        try:
            barrier.wait()  # maximize real overlap on the row-lock window
            event = record_event(session, product_id, EventType.PURCHASE, 10, "race-event", None, 1)
            results[i] = event.id
        finally:
            session.close()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r is not None for r in results)
    # All N calls must resolve to the exact same event row — one real
    # insert, N-1 idempotent replays, not N separate rows.
    assert len(set(results)) == 1

    db.expire_all()
    rows = (
        db.query(InventoryEvent)
        .filter(InventoryEvent.event_id == "race-event", InventoryEvent.organization_id == 1)
        .all()
    )
    assert len(rows) == 1

    state = db.query(InventoryState).filter(InventoryState.product_id == product_id).first()
    assert state.quantity == 10  # applied once, not thread_count times


@pytest.mark.postgres
def test_concurrent_same_event_id_different_orgs_no_false_reject(db, second_org):
    """
    The other half of the concurrency risk in issue #142: two different
    orgs recording the same literal event_id concurrently must not
    false-positive-reject each other — org-scoped UNIQUE(organization_id,
    event_id) means there's no shared constraint window between them to
    race on in the first place, but this proves it under real concurrent
    load, not just two sequential requests.
    """
    org1_product = Product(
        organization_id=1, name="Org1 Concurrency Widget", sku="org1-concurrency-widget"
    )
    org2_product = Product(
        organization_id=second_org.id,
        name="Org2 Concurrency Widget",
        sku="org2-concurrency-widget",
    )
    db.add_all([org1_product, org2_product])
    db.commit()
    db.refresh(org1_product)
    db.refresh(org2_product)

    barrier = threading.Barrier(2)
    results = {}
    errors = {}

    def _worker(key, product_id, organization_id):
        session = TestingSessionLocal()
        try:
            barrier.wait()
            event = record_event(
                session,
                product_id,
                EventType.PURCHASE,
                15,
                "shared-race-event-id",
                None,
                organization_id,
            )
            results[key] = event.id
        except Exception as e:  # noqa: BLE001 — captured for the assertion below, not swallowed
            errors[key] = e
        finally:
            session.close()

    t1 = threading.Thread(target=_worker, args=("org1", org1_product.id, 1))
    t2 = threading.Thread(target=_worker, args=("org2", org2_product.id, second_org.id))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == {}
    assert "org1" in results and "org2" in results

    db.expire_all()
    org1_rows = (
        db.query(InventoryEvent)
        .filter(
            InventoryEvent.event_id == "shared-race-event-id", InventoryEvent.organization_id == 1
        )
        .all()
    )
    org2_rows = (
        db.query(InventoryEvent)
        .filter(
            InventoryEvent.event_id == "shared-race-event-id",
            InventoryEvent.organization_id == second_org.id,
        )
        .all()
    )
    assert len(org1_rows) == 1
    assert len(org2_rows) == 1


@pytest.mark.postgres
def test_concurrent_distinct_events_same_product_no_lost_updates(db):
    """
    Targets _apply_event()'s with_for_update() row lock specifically —
    the other two concurrency tests above only exercise the org-scoped
    unique constraint (they'd still pass with the lock removed, since
    duplicate event_ids collide on the constraint regardless of locking).
    This one uses N *distinct* event_ids concurrently modifying the same
    product's inventory_state row: without a real row lock, a classic
    read-modify-write race can lose updates (two threads both read the
    same starting quantity before either commits, so one thread's
    increment overwrites the other's instead of both applying). The
    final quantity must equal the sum of every applied delta.

    The first event is applied synchronously, outside the race, so the
    inventory_state row already exists before the concurrent workers
    start — with_for_update() only ever locks a row that already exists;
    a *first-ever* event for a product racing on row *creation* is a
    separate, pre-existing race (a plain INSERT primary-key collision,
    unrelated to Epoch 10 or this lock) that this test deliberately
    doesn't exercise.
    """
    product = Product(organization_id=1, name="Lost Update Widget", sku="lost-update-widget")
    db.add(product)
    db.commit()
    db.refresh(product)
    product_id = product.id

    thread_count = 8
    delta = 10
    record_event(db, product_id, EventType.PURCHASE, delta, "race-event-seed", None, 1)

    barrier = threading.Barrier(thread_count)

    def _worker(i):
        session = TestingSessionLocal()
        try:
            barrier.wait()
            record_event(session, product_id, EventType.PURCHASE, delta, f"race-event-{i}", None, 1)
        finally:
            session.close()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    db.expire_all()
    state = db.query(InventoryState).filter(InventoryState.product_id == product_id).first()
    # seed event + thread_count racing events, each +delta — if any got
    # lost to the race, this comes up short.
    assert state.quantity == delta * (thread_count + 1)
