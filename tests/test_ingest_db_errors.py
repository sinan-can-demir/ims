# Batch ingest must survive DB errors per-row instead of 500ing the request
# after earlier rows already committed (#392).

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.inventory_event import InventoryEvent
from app.services import ingestion_service
from app.services.ingestion_service import ingest_events

from .utils import create_product


class _PgError(Exception):
    def __init__(self, pgcode):
        super().__init__("raw driver text SELECT secret FROM t")
        self.pgcode = pgcode


def _op_error(pgcode):
    return OperationalError("SELECT 1", {}, _PgError(pgcode))


def _rows(sku, n=3):
    return [
        {"sku": sku, "event_type": "PURCHASE", "quantity": 1, "event_id": f"db-err-{i}"}
        for i in range(n)
    ]


def test_persistent_db_error_fails_only_that_row(client, db, monkeypatch):
    product = create_product(client)
    real = ingestion_service.record_event

    def flaky(db_, product_id, event_type, quantity, event_id, *a, **kw):
        if event_id == "db-err-1":
            raise IntegrityError("INSERT", {}, _PgError("23503"))
        return real(db_, product_id, event_type, quantity, event_id, *a, **kw)

    monkeypatch.setattr(ingestion_service, "record_event", flaky)
    out = ingest_events(db, _rows(product["sku"]))

    assert [r["status"] for r in out["results"]] == ["success", "failed", "success"]
    assert out["rows_succeeded"] == 2 and out["rows_failed"] == 1
    err = out["results"][1]["error"]
    assert "SELECT" not in err and "secret" not in err  # no driver text leaks
    ids = {e.event_id for e in db.query(InventoryEvent).all()}
    assert {"db-err-0", "db-err-2"} <= ids and "db-err-1" not in ids


def test_deadlock_is_retried_once_then_succeeds(client, db, monkeypatch):
    product = create_product(client)
    real = ingestion_service.record_event
    calls = {"n": 0}

    def deadlock_once(db_, product_id, event_type, quantity, event_id, *a, **kw):
        if event_id == "db-err-0":
            calls["n"] += 1
            if calls["n"] == 1:
                raise _op_error("40P01")
        return real(db_, product_id, event_type, quantity, event_id, *a, **kw)

    monkeypatch.setattr(ingestion_service, "record_event", deadlock_once)
    out = ingest_events(db, _rows(product["sku"], 2))

    assert calls["n"] == 2
    assert out["rows_succeeded"] == 2 and out["rows_failed"] == 0


def test_deadlock_twice_fails_row_not_request(client, db, monkeypatch):
    product = create_product(client)
    real = ingestion_service.record_event
    calls = {"n": 0}

    def always_deadlock(db_, product_id, event_type, quantity, event_id, *a, **kw):
        if event_id == "db-err-0":
            calls["n"] += 1
            raise _op_error("40P01")
        return real(db_, product_id, event_type, quantity, event_id, *a, **kw)

    monkeypatch.setattr(ingestion_service, "record_event", always_deadlock)
    out = ingest_events(db, _rows(product["sku"], 2))

    assert calls["n"] == 2  # exactly one retry, no loop
    assert [r["status"] for r in out["results"]] == ["failed", "success"]


@pytest.mark.parametrize("pgcode", ["57014", "08006", None])
def test_non_retryable_db_error_is_not_retried(client, db, monkeypatch, pgcode):
    product = create_product(client)
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        raise _op_error(pgcode)

    monkeypatch.setattr(ingestion_service, "record_event", boom)
    out = ingest_events(db, _rows(product["sku"], 1))

    assert calls["n"] == 1
    assert out["results"][0]["status"] == "failed"


@pytest.mark.postgres
def test_real_postgres_deadlock_is_retried_and_batch_survives(db, monkeypatch):
    """
    A real deadlock, not a mocked one. A dish's SALE cascade locks the dish,
    then ingredient X, then ingredient Y. A second transaction holds Y and
    then asks for X, forming a cycle. Postgres aborts the ingest's
    transaction (its deadlock_timeout timer started first); ingest_events
    must retry that row once and succeed, and the rest of the batch must
    be unaffected.
    """
    import threading
    import time

    from sqlalchemy import text

    from app.models.inventory_state import InventoryState
    from app.models.product import Product
    from app.models.recipe_item import RecipeItem

    from .conftest import TestingSessionLocal

    def _product(name):
        p = Product(organization_id=1, name=name, sku=name)
        db.add(p)
        db.flush()
        db.add(InventoryState(product_id=p.id, quantity=100, organization_id=1))
        return p

    dish, x, y, plain = (_product(n) for n in ("dl-dish", "dl-x", "dl-y", "dl-plain"))
    db.flush()
    db.add(
        RecipeItem(
            finished_product_id=dish.id, component_product_id=x.id, quantity=1, organization_id=1
        )
    )
    db.add(
        RecipeItem(
            finished_product_id=dish.id, component_product_id=y.id, quantity=1, organization_id=1
        )
    )
    db.commit()
    ids = {"x": x.id, "y": y.id}

    y_locked = threading.Event()
    blocker_errors = []

    def blocker():
        s = TestingSessionLocal()
        try:
            s.execute(
                text("SELECT 1 FROM inventory_state WHERE product_id = :p FOR UPDATE"),
                {"p": ids["y"]},
            )
            y_locked.set()
            time.sleep(0.7)  # let the ingest block on Y first
            s.execute(
                text("SELECT 1 FROM inventory_state WHERE product_id = :p FOR UPDATE"),
                {"p": ids["x"]},
            )
            s.commit()
        except Exception as e:  # noqa: BLE001 -- surfaced via the assert below
            blocker_errors.append(e)
            s.rollback()
        finally:
            s.close()

    calls = []
    real = ingestion_service.record_event

    def counting(db_, product_id, event_type, quantity, event_id, *a, **kw):
        calls.append(event_id)
        return real(db_, product_id, event_type, quantity, event_id, *a, **kw)

    monkeypatch.setattr(ingestion_service, "record_event", counting)

    t = threading.Thread(target=blocker)
    t.start()
    assert y_locked.wait(10)

    session = TestingSessionLocal()
    try:
        out = ingest_events(
            session,
            [
                {"sku": "dl-dish", "event_type": "SALE", "quantity": 1, "event_id": "dl-sale"},
                {"sku": "dl-plain", "event_type": "PURCHASE", "quantity": 1, "event_id": "dl-ok"},
            ],
        )
    finally:
        session.close()
        t.join()

    assert not blocker_errors, blocker_errors  # blocker must not have been the victim
    assert calls.count("dl-sale") == 2, calls  # deadlocked once, retried once
    assert out["rows_succeeded"] == 2 and out["rows_failed"] == 0, out
