# tests/test_rate_limit.py

from contextlib import contextmanager

from slowapi.wrappers import LimitGroup
from starlette.requests import Request

from app.core.rate_limit import rate_limit_key
from app.main import app


@contextmanager
def _tight_limit(limit_string: str):
    """
    Temporarily overrides the app's real limiter (app.main wires the same
    singleton into app.state.limiter) with a low threshold so tests can
    trigger a 429 without hundreds of requests, then restores it.
    """
    limiter = app.state.limiter
    original = limiter._default_limits
    limiter._default_limits = [
        LimitGroup(limit_string, limiter._key_func, None, False, None, None, None, 1, False)
    ]
    limiter.reset()
    try:
        yield limiter
    finally:
        limiter._default_limits = original
        limiter.reset()


def test_requests_within_limit_pass(client):
    with _tight_limit("3/minute"):
        for _ in range(3):
            assert client.get("/api/inventory/1").status_code != 429


def test_limit_exceeded_returns_429(client):
    with _tight_limit("2/minute"):
        statuses = [client.get("/api/inventory/1").status_code for _ in range(3)]

        assert 429 in statuses


def test_limit_exceeded_response_has_clear_message(client):
    with _tight_limit("1/minute"):
        client.get("/api/inventory/1")
        response = client.get("/api/inventory/1")

        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["error"]


def test_health_and_metrics_are_exempt(client):
    """Docker HEALTHCHECK and Prometheus scraping must never get 429'd."""
    with _tight_limit("1/minute"):
        for _ in range(5):
            assert client.get("/health").status_code == 200
            assert client.get("/metrics").status_code == 200


def test_key_func_ignores_presented_bearer_token():
    """
    A different bearer token (or account) on every request must not grant
    a fresh bucket — otherwise brute-forcing login trivially bypasses the
    limit by rotating credentials.
    """
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer guess-1")],
        "client": ("1.2.3.4", 1234),
    }
    other_scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer guess-2")],
        "client": ("1.2.3.4", 1234),
    }
    assert rate_limit_key(Request(scope)) == rate_limit_key(Request(other_scope))


def test_key_func_uses_client_ip():
    scope = {"type": "http", "headers": [], "client": ("1.2.3.4", 1234)}
    request = Request(scope)
    assert rate_limit_key(request) == "1.2.3.4"
