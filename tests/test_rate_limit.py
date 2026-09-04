# tests/test_rate_limit.py

import uuid
from contextlib import contextmanager

from slowapi.wrappers import LimitGroup
from starlette.requests import Request

from app.core.rate_limit import rate_limit_key, webhook_limiter
from app.main import app

from .utils import create_product
from .utils import set_webhook_secret as _set_webhook_secret
from .utils import signed_webhook_request as _signed_webhook_request


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


def test_key_func_trusts_forwarded_for_from_private_peer():
    """
    A private-address peer is our own reverse proxy (Caddy over the
    Compose network, ALB over its VPC) — trust the real client IP it
    forwarded.
    """
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"9.9.9.9")],
        "client": ("172.18.0.5", 1234),
    }
    assert rate_limit_key(Request(scope)) == "9.9.9.9"


def test_key_func_ignores_forwarded_for_from_public_peer():
    """
    The no-Caddy plain-HTTP deployment path has no proxy in front at all
    — a direct internet client could forge X-Forwarded-For themselves to
    reset their own bucket every request. A public peer is never trusted
    to supply this header; use the real TCP peer instead.
    """
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"9.9.9.9")],
        "client": ("1.2.3.4", 1234),
    }
    assert rate_limit_key(Request(scope)) == "1.2.3.4"


def test_key_func_uses_leftmost_forwarded_for_entry():
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"9.9.9.9, 172.18.0.5")],
        "client": ("172.18.0.5", 1234),
    }
    assert rate_limit_key(Request(scope)) == "9.9.9.9"


def test_key_func_falls_back_to_peer_when_no_forwarded_for_header():
    scope = {"type": "http", "headers": [], "client": ("172.18.0.5", 1234)}
    assert rate_limit_key(Request(scope)) == "172.18.0.5"


@contextmanager
def _tight_webhook_limit(limit_string: str):
    """Same idiom as _tight_limit above, but for the separate webhook_limiter instance."""
    original = webhook_limiter._default_limits
    webhook_limiter._default_limits = [
        LimitGroup(limit_string, webhook_limiter._key_func, None, False, None, None, None, 1, False)
    ]
    webhook_limiter.reset()
    try:
        yield webhook_limiter
    finally:
        webhook_limiter._default_limits = original
        webhook_limiter.reset()


def _webhook_payload(sku):
    return {
        "source": "generic",
        "events": [
            {
                "sku": sku,
                "event_type": "PURCHASE",
                "quantity": 1,
                "external_id": f"txn-{uuid.uuid4()}",
            }
        ],
    }


_ORG1_WEBHOOK_SECRET = "org1-secret"  # noqa: S105 -- test fixture value, not a real credential
_ORG2_WEBHOOK_SECRET = "org2-secret"  # noqa: S105 -- test fixture value, not a real credential


def test_webhook_rate_limit_is_isolated_per_org(client, client_org2, db, second_org):
    """
    One org flooding its webhook route must not exhaust the bucket for a
    different org — proves enforce_webhook_rate_limit's per-org keying
    (organization_id path param, not client IP) actually isolates them,
    the whole point of not reusing the client-IP-keyed `limiter` here.
    """
    _set_webhook_secret(db, 1, _ORG1_WEBHOOK_SECRET)
    _set_webhook_secret(db, second_org.id, _ORG2_WEBHOOK_SECRET)
    org1_product = create_product(client, "Org1 Widget")
    org2_product = create_product(client_org2, "Org2 Widget")

    with _tight_webhook_limit("1/minute"):
        first = _signed_webhook_request(
            client, 1, _webhook_payload(org1_product["sku"]), secret=_ORG1_WEBHOOK_SECRET
        )
        assert first.status_code == 200

        flooded = _signed_webhook_request(
            client, 1, _webhook_payload(org1_product["sku"]), secret=_ORG1_WEBHOOK_SECRET
        )
        assert flooded.status_code == 429

        # Org 2's own bucket is untouched by org 1's flood.
        other_org = _signed_webhook_request(
            client_org2,
            second_org.id,
            _webhook_payload(org2_product["sku"]),
            secret=_ORG2_WEBHOOK_SECRET,
        )
        assert other_org.status_code == 200
