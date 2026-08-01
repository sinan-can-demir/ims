import os
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Prefer the matched route template (e.g. "/api/products/{product_id}")
        # over the raw path, so per-entity IDs don't blow up label cardinality.
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path

        REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(duration)
        return response


def metrics_response() -> Response:
    # Gunicorn runs multiple worker processes in production, each with its own
    # in-memory registry. PROMETHEUS_MULTIPROC_DIR (set in deploy/docker-compose.prod.yml)
    # tells prometheus_client to shard counters to disk instead, so a scrape can
    # merge every worker's data — see config/gunicorn.conf.py for the matching cleanup hooks.
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(data, media_type=CONTENT_TYPE_LATEST)
