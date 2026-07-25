# app/core/rate_limit.py

import os

from slowapi import Limiter
from starlette.requests import Request

_DEFAULT_RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")


def rate_limit_key(request: Request) -> str:
    """
    Always keys by client IP, never by anything in the request itself
    (bearer token, headers). Keying by a client-supplied value would let
    an attacker reset their bucket on every request just by presenting a
    different value each time — e.g. a different account's token, or a
    guessed header — defeating the brute-force mitigation this is meant
    to provide, most concretely on the unauthenticated POST
    /api/auth/login itself.
    """
    return request.client.host if request.client else "unknown"


# Storage defaults to slowapi's in-process memory:// backend, which is not
# shared across Gunicorn's worker processes in prod (WEB_CONCURRENCY,
# docker-compose.prod.yml) — same class of gap PROMETHEUS_MULTIPROC_DIR
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
