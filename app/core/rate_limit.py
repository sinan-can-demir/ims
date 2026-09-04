# app/core/rate_limit.py

import ipaddress
import os

from slowapi import Limiter
from starlette.requests import Request

_DEFAULT_RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")

# Every documented deployment path puts at most one reverse proxy between
# the real client and this app, and that proxy always connects over a
# private network: Caddy over the Docker Compose network (self-hosted +
# deploy/Caddyfile overlay), the ALB over its VPC (10.0.0.0/16, infra/variables.tf).
# The one path with no proxy at all — deploy/docker-compose.prod.yml alone,
# plain HTTP on :8000 (see deploy/docker-compose.caddy.yml's comment) — has
# Docker's published-port NAT preserve the real public client IP as the
# TCP peer already, no header needed. So: trust X-Forwarded-For's
# leftmost entry only when the immediate TCP peer is itself a private
# address — that's exactly the case where "the peer" is our own proxy,
# not an internet client who could forge the header themselves.
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
)


def _is_trusted_proxy_peer(peer_ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(addr in network for network in _PRIVATE_NETWORKS)


def rate_limit_key(request: Request) -> str:
    """
    Keys by the real client IP — see _is_trusted_proxy_peer's docstring
    for why X-Forwarded-For is only trusted when the connecting peer is
    itself private (our own reverse proxy), never unconditionally.
    Keying by anything client-supplied without that check would let an
    attacker reset their bucket on every request just by presenting a
    different value each time — e.g. a different account's token, or (if
    trusted blindly) a forged X-Forwarded-For header — defeating the
    brute-force mitigation this is meant to provide, most concretely on
    the unauthenticated POST /api/auth/login itself.
    """
    peer_ip = request.client.host if request.client else None

    if peer_ip and _is_trusted_proxy_peer(peer_ip):
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Leftmost entry is the original client, appended by the
            # first (and here, only) proxy hop — revisit this index if a
            # second hop (e.g. a CDN) is ever added in front of Caddy/ALB.
            return forwarded_for.split(",")[0].strip()

    return peer_ip or "unknown"


# Storage defaults to slowapi's in-process memory:// backend, which is not
# shared across Gunicorn's worker processes in prod (WEB_CONCURRENCY,
# deploy/docker-compose.prod.yml) — same class of gap PROMETHEUS_MULTIPROC_DIR
# exists to solve for /metrics, unaddressed here. Effective limit in prod
# is therefore ~WEB_CONCURRENCY x RATE_LIMIT, not exactly RATE_LIMIT. See
# SECURITY.md.
limiter = Limiter(key_func=rate_limit_key, default_limits=[_DEFAULT_RATE_LIMIT])


def enforce_rate_limit(request: Request) -> None:
    """
    Attached as a per-router Depends() (see app/main.py) instead of
    slowapi's SlowAPIMiddleware. Middleware runs *before* routing, so it
    has to guess which route matched by walking app.routes itself —
    FastAPI 0.140+ wraps include_router()-added routes in a private
    _IncludedRouter object that walk can't see into, so the middleware
    silently stopped rate-limiting every /api route on newer FastAPI (see
    #66). A dependency runs *after* routing has already resolved the
    endpoint, so it needs none of that route-matching machinery — it just
    calls the same check slowapi's own @limiter.limit(...) decorator uses.
    """
    limiter._check_request_limit(request, None, True)


_WEBHOOK_DEFAULT_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "60/minute")


def webhook_rate_limit_key(request: Request) -> str:
    """
    Keyed on the target organization_id path param, not client IP.
    Webhook senders (POS/e-commerce platforms) commonly deliver from a
    shared pool of egress IPs across many merchants — IP-keying here
    would let one busy org's traffic exhaust the bucket for an unrelated
    org whose sender happens to share the same egress infrastructure.
    Per-org keying isolates each org's own rate limit from every other
    org's, matching this app's general multi-tenancy posture elsewhere.
    """
    return str(request.path_params.get("organization_id", "unknown"))


# Separate Limiter instance (own bucket namespace) from `limiter` above —
# a shared instance would mix webhook traffic into the same keyspace as
# authenticated /api requests, and the two need different keying
# entirely (org id vs. client IP).
webhook_limiter = Limiter(
    key_func=webhook_rate_limit_key, default_limits=[_WEBHOOK_DEFAULT_RATE_LIMIT]
)


def enforce_webhook_rate_limit(request: Request) -> None:
    """
    Same per-route Depends() idiom as enforce_rate_limit — see its
    docstring for why middleware doesn't work here. Applied directly on
    the webhook route (not router-level like `_auth` in app/main.py)
    because the key function needs {organization_id}, which is only
    resolved once FastAPI has matched this specific route.
    """
    webhook_limiter._check_request_limit(request, None, True)
