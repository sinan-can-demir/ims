# Observability

The API exposes Prometheus metrics and emits structured JSON logs with a
per-request correlation ID, so a slow or failing request can be traced from a
dashboard alert back to the exact log lines that explain it.

## Metrics

`GET /metrics` (unauthenticated, alongside `/health`) serves Prometheus
[text-format](https://prometheus.io/docs/instrumenting/exposition_formats/)
output via `app/core/metrics.py`:

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `path`, `status` | Requests served |
| `http_request_duration_seconds` | Histogram | `method`, `path` | Request latency |

`path` is the matched route template (e.g. `/api/products/{product_id}`), not
the raw URL, so per-entity IDs don't create a new label series per request.

A minimal scrape config:

```yaml
scrape_configs:
  - job_name: ims-api
    static_configs:
      - targets: ["api:8000"]
```

`/metrics` isn't behind bearer-token auth — treat it the same as `/health`:
fine on a private network or behind the reverse proxy, not something to
expose publicly without a firewall rule or its own auth in front.

### Multiprocess mode (production only)

`deploy/docker-compose.prod.yml` runs the API under Gunicorn with multiple
`UvicornWorker` processes (see `WEB_CONCURRENCY`). Each worker process has
its own Python memory space, so without extra wiring each one would report
only the requests *it* handled, and a scrape would just see whichever worker
answered that connection.

`prometheus_client`'s multiprocess mode fixes this by having every worker
write to shared mmap'd files instead of an in-memory registry, which
`metrics_response()` then merges on scrape. It's wired via:

- `PROMETHEUS_MULTIPROC_DIR` — set in `deploy/docker-compose.prod.yml`, tells
  `prometheus_client` where to put those files.
- `config/gunicorn.conf.py` — `on_starting` clears stale files left over
  from a previous run (they'd otherwise double-count after a restart);
  `child_exit` removes a worker's files when it exits (worker recycling,
  crashes) so dead workers don't leak stale series into the merged output.

The base `deploy/docker-compose.yml` dev command runs a single Uvicorn process with
`PROMETHEUS_MULTIPROC_DIR` unset, so `metrics_response()` falls back to the
default in-process registry — no multiprocess setup needed locally.

## Structured logging

`app/core/logging.py` formats every log line as JSON
(`python-json-logger`), and `RequestLoggingMiddleware` logs one
`request_completed` event per request:

```json
{"asctime": "...", "levelname": "INFO", "name": "ims", "message": "request_completed",
 "request_id": "b3f1...", "method": "GET", "path": "/api/inventory/1",
 "status_code": 200, "duration_ms": 4.21}
```

The same `request_id` is also returned as an `X-Request-ID` response header,
and application code can attach it to its own log lines via
`request.state.request_id` — useful for tying a service-layer error (e.g.
`forecast_failed` in `app/api/forecast.py`) back to the request that
triggered it.

`/health` and `/metrics` are excluded from this access log — both are
scraped or polled frequently by infra (Docker `HEALTHCHECK`, Prometheus) and
would otherwise drown out real traffic in the logs.
