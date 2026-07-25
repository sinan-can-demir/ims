# tests/test_metrics.py

import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_metrics_endpoint_is_unauthenticated():
    """Prometheus scrapers don't send a bearer token — /metrics must stay exempt, like /health."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_returns_prometheus_format():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/metrics")
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_request_is_counted_by_path_and_method():
    client = TestClient(app, raise_server_exceptions=False)
    client.get("/health")
    body = client.get("/metrics").text
    assert 'method="GET"' in body
    assert 'path="/health"' in body


def test_response_has_request_id_header():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")
    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    uuid.UUID(request_id)  # raises ValueError if not a valid UUID


def test_each_request_gets_a_distinct_request_id():
    client = TestClient(app, raise_server_exceptions=False)
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert first != second
