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
# rightmost entry (the one our own proxy appended) only when the
# immediate TCP peer is itself a private address — that's exactly the
# case where "the peer" is our own proxy, not an internet client who
# could forge the header themselves.
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
            # RIGHTMOST entry, not leftmost (#387). Each proxy appends the
            # address of whoever connected to it, so the right end is the
            # one our own proxy wrote; everything to its left is whatever
            # the client chose to send and can be forged. Reading the left
            # end let an attacker behind the ALB (which appends to, rather
            # than replaces, a client-supplied header) get a fresh
            # rate-limit bucket on every request.
            #
            # ASSUMPTION — EXACTLY ONE TRUSTED PROXY HOP in front of this
            # app (Caddy or the ALB). If a second hop is ever added (a CDN
            # or WAF in front of the ALB/Caddy), the rightmost entry becomes
            # the FIRST proxy's address, every real client collapses into
            # one shared bucket, and one noisy client can rate-limit
            # everyone. At that point this must change to "skip N trusted
            # hops from the right" (a configurable hop count). Revisit
            # before adding any second proxy. See SECURITY.md.
            return forwarded_for.split(",")[-1].strip()
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
# Generous on purpose: POS senders share egress IPs across many merchants,
# so this is only a flood ceiling in front of the HMAC check, not the
# real per-tenant throttle (that's WEBHOOK_RATE_LIMIT, charged only after
# the signature verifies).
_WEBHOOK_IP_DEFAULT_RATE_LIMIT = os.getenv("WEBHOOK_IP_RATE_LIMIT", "600/minute")


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

    Must run AFTER require_webhook_signature (#386). The bucket is keyed
    by the org id from the URL, which anyone can put in a request; if
    unsigned requests were charged to it, an attacker with no secret could
    exhaust a victim org's bucket and make that org's real, signed
    deliveries get 429. Unsigned requests are bounced by the signature
    check (401) before reaching this, so only authenticated traffic
    spends the org's budget.
    """
    webhook_limiter._check_request_limit(request, None, True)


# Own Limiter (own bucket namespace), keyed by client IP — the cheap
# flood ceiling that sits in front of the signature check, so unsigned
# floods are still rejected without paying for an HMAC + DB lookup each
# time. Reuses rate_limit_key, so it inherits that function's
# X-Forwarded-For trust rules (and #387's caveats).
webhook_ip_limiter = Limiter(
    key_func=rate_limit_key, default_limits=[_WEBHOOK_IP_DEFAULT_RATE_LIMIT]
)


def enforce_webhook_ip_rate_limit(request: Request) -> None:
    """Per-IP ceiling for the webhook route; runs BEFORE the signature check."""
    webhook_ip_limiter._check_request_limit(request, None, True)
