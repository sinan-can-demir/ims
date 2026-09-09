# tests/test_error_handling.py

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.logging import logger


def _non_raising_client(client) -> TestClient:
    """Starlette's ServerErrorMiddleware always re-raises after running a
    registered handler (deliberately, so the default TestClient can
    surface tracebacks for debugging) — raise_server_exceptions=False is
    what makes it return the handler's actual response instead, which is
    what these tests need to assert against."""
    return TestClient(client.app, headers=client.headers, raise_server_exceptions=False)


def test_unhandled_exception_returns_generic_500(client):
    with patch("app.api.products.list_products", side_effect=RuntimeError("boom")):
        response = _non_raising_client(client).get("/api/products")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "X-Request-ID" in response.headers


def test_unhandled_exception_is_logged_with_traceback_and_request_id(client, caplog):
    with (
        patch("app.api.products.list_products", side_effect=RuntimeError("boom")),
        caplog.at_level("ERROR", logger=logger.name),
    ):
        response = _non_raising_client(client).get("/api/products")

    records = [r for r in caplog.records if r.message == "unhandled_exception"]
    assert len(records) == 1
    record = records[0]
    assert record.request_id == response.headers["X-Request-ID"]
    assert record.path == "/api/products"
    assert record.exception_type == "RuntimeError"
    assert "RuntimeError: boom" in record.traceback


def test_domain_error_is_unaffected_by_catch_all_handler(client):
    """A specific DomainError subclass (e.g. duplicate SKU -> 409) must
    still be handled by its own handler, not swallowed by the new
    catch-all Exception handler."""
    payload = {"name": "Widget", "sku": "WID-1"}
    client.post("/api/products", json=payload)
    response = client.post("/api/products", json=payload)

    assert response.status_code == 409
