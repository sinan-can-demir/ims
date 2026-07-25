# IMS — Inventory Management System

[![CI](https://github.com/sinan-can-demir/ims-manual/actions/workflows/ci.yml/badge.svg)](https://github.com/sinan-can-demir/ims-manual/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An event-driven inventory platform with a full analytics pipeline and ML-powered demand forecasting. Built from scratch as a learning project covering data engineering, backend systems, and machine learning.

**Stack:** FastAPI · PostgreSQL · dbt · DuckDB · Prophet · Streamlit · Docker

> **Project status:** actively developed learning project, not a hardened production system.
> Auth is a single shared API key (see [SECURITY.md](SECURITY.md) for what that does and doesn't protect against). Deployment beyond local Docker is in progress ([Epoch 7](ROADMAP.md)) — see [Deployment](#deployment) below.

---

## What Works Now

- [x] Event-sourced inventory core — append-only `InventoryEvent` log +
      `InventoryState` projection, idempotent writes (`event_id`), oversell
      protection
- [x] Product + inventory REST API (FastAPI/Postgres), API-key auth
- [x] Bulk CSV import (`POST /api/inventory/events/bulk`) — per-row partial
      success
- [x] Generic HMAC-signed webhook ingestion (`POST /api/webhooks/ingest`)
- [x] Full analytics pipeline: Parquet data lake → DuckDB warehouse → dbt
      models + data quality tests
- [x] Prophet demand forecasting per product, tracked in an MLflow model
      registry
- [x] Streamlit dashboard — live inventory, event history, 30-day forecasts
- [x] Prometheus metrics + structured JSON request logging
      (`/metrics`, `X-Request-ID`)
- [x] CI on every push/PR — lint, full test suite (incl. Postgres-only
      tests), Docker build, dependency/secret/image vulnerability scanning
      (Dependabot + gitleaks + pip-audit + trivy), and a dedicated pipeline
      job exercising export → warehouse → dbt against a real Postgres
- [x] Self-hosted deployment path (Docker Compose + optional Caddy HTTPS)
- [x] Dashboard deployed alongside the API in the self-hosted stack, gated
      behind Caddy basic auth (the dashboard has no auth of its own)
- [x] Security response headers (X-Frame-Options, X-Content-Type-Options,
      Referrer-Policy, conditional HSTS)
- [x] Rate limiting on `/api` routes (slowapi, keyed by client IP) — see
      [SECURITY.md](SECURITY.md) for a known compatibility limitation with
      newer FastAPI versions

## In Progress

- [ ] Move the data lake off the local filesystem onto S3-compatible object
      storage
- [ ] Deploy the dashboard on AWS (ECS, reading the feature store from S3)
- [ ] Apply the AWS Terraform — ECS/RDS/ALB infra is written, not yet running
- [ ] Replace shared API-key auth with JWT/OIDC

See [ROADMAP.md](ROADMAP.md) for the full backlog.

---

## What it does

- Tracks inventory changes as an **immutable event log** (event sourcing + CQRS)
- Exports events to a **Parquet data lake**, transforms them in a **DuckDB warehouse** via dbt
- Trains a **Prophet forecasting model** per product on historical demand
- Serves a **Streamlit dashboard** with live inventory levels, event history, and 30-day demand forecasts

<!--
TODO: add a screenshot/GIF of the dashboard here once available.
  1. make dashboard
  2. screenshot the running app
  3. save under docs/images/dashboard.png
  4. replace this comment with: ![Dashboard](docs/images/dashboard.png)
-->

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      WRITE PATH                              │
│   Client → POST /api/inventory/events                        │
│          → inventory_events (append-only)                    │
│          → inventory_state  (projection, same transaction)   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                      READ PATH                               │
│   Client → GET /api/inventory/{product_id}                   │
│          → inventory_state (O(1) pre-computed projection)    │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                   ANALYTICS PIPELINE                         │
│   PostgreSQL → Parquet (data lake)                           │
│             → DuckDB  (warehouse)                            │
│             → dbt     (dim/fact models + data quality tests) │
│             → Prophet (demand forecast per product)          │
│             → Streamlit dashboard                            │
└──────────────────────────────────────────────────────────────┘
```

### Core concepts

| Concept | Description |
|---|---|
| `InventoryEvent` | Immutable ledger entry for every stock change |
| `InventoryState` | Pre-computed projection — reads are O(1), no aggregation at query time |
| `event_id` | Client-provided UUID for idempotent writes |
| dbt models | Dimensional warehouse (products, dates, daily snapshots) built on DuckDB |
| Feature store | Lag features + rolling averages prepared for ML training |
| Prophet model | Per-product demand forecasting with 30-day horizon |

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Database | PostgreSQL 15 + SQLAlchemy + Alembic |
| Validation | Pydantic |
| Data lake | Parquet files |
| Warehouse | DuckDB + dbt |
| ML | Prophet (Meta) |
| Dashboard | Streamlit |
| Containerization | Docker + Docker Compose |
| Testing | Pytest + httpx |

---

## Project Structure

```
ims-manual/
├── app/                    # FastAPI application
│   ├── api/                # Route handlers (products, inventory)
│   ├── models/             # SQLAlchemy models
│   ├── schemas/            # Pydantic schemas
│   └── services/           # Business logic
├── migrations/             # Alembic migrations
├── tests/                  # Unit, integration, and e2e tests
├── pipelines/              # PostgreSQL → Parquet export
├── data_lake/              # Parquet event snapshots
├── warehouse/              # DuckDB + dbt project
│   └── ims_warehouse/
│       ├── models/         # dbt dim/fact models
│       └── tests/          # dbt data quality tests
├── feature_store/          # Engineered features for ML
├── models/                 # Trained Prophet model artifacts (gitignored — run `make train` to generate)
├── mlflow.db, mlruns/      # MLflow model registry (gitignored — see docs/model-registry.md)
├── dashboard/              # Streamlit app
├── docker/                 # Dockerfile
├── docker-compose.yml            # local dev
├── docker-compose.prod.yml       # self-hosted prod hardening (overlay)
├── docker-compose.caddy.yml      # optional automatic HTTPS (overlay)
├── docs/deployment/        # self-hosted deployment guide
├── docs/model-registry.md  # MLflow setup, promotion/rollback
├── docs/observability.md   # Prometheus metrics, structured request logging
├── infra/                  # Terraform for AWS (enterprise deployment)
├── Makefile                # One-command dev workflow
├── requirements.txt
└── requirements-train.txt  # extra deps for `make train` only (mlflow-skinny)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose

### Quickstart (Docker)

```bash
# Start PostgreSQL + API
make up

# Run migrations
make migrate

# Create an account — no self-service registration, every /api route and
# the dashboard both require this (see API Reference and SECURITY.md)
python scripts/create_user.py --email you@example.com --display-name "Your Name"

# Seed some data, then run the full pipeline
make export       # PostgreSQL → Parquet
make warehouse    # build DuckDB warehouse tables
make dbt-run      # run dbt transformations
make dbt-test     # run data quality tests
make features     # build feature store
make train-deps   # one-off: install mlflow-skinny for the model registry
make train        # train Prophet models, logged to the MLflow registry

# Launch dashboard
streamlit run dashboard/app.py
```

### Local Development (no Docker)

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ims"
alembic upgrade head
python scripts/create_user.py --email you@example.com --display-name "Your Name"
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`. Get a bearer token via
`POST /api/auth/login`, then pass `Authorization: Bearer <token>` on every
other `/api` request — see [API Reference](#api-reference).

---

## Deployment

Two paths, depending on what you're running this for:

- **[Self-hosted](docs/deployment/self-hosted.md)** (recommended default) —
  any VPS, ~$5-20/month, no cloud account, fully open-source tooling
  (Docker Compose + optional [Caddy](https://caddyserver.com/) for automatic
  HTTPS). Lowest barrier to actually running this for real use.
- **[AWS](infra/README.md)** (enterprise) — Terraform for ECS Fargate + RDS +
  ALB with least-privilege IAM and OIDC-based CI/CD, for teams already
  running on AWS. More capable (managed failover, autoscaling headroom) and
  more expensive (~$75-85/month) than the self-hosted path.

Both deploy the same Docker image; neither is required to run the project
locally (see Getting Started above).

---

## API Reference

All routes below live under `/api` and require an `Authorization: Bearer
<token>` header — get a token from `POST /api/auth/login` (see
[Environment Variables](#environment-variables) and
[SECURITY.md](SECURITY.md)). `/health` and `/metrics` (Prometheus format —
see [docs/observability.md](docs/observability.md)) are always
unauthenticated.

### Products

```http
POST /api/products
{ "name": "Widget A", "sku": "WGT-001" }
```

### Inventory Events

```http
POST /api/inventory/events
{
    "product_id": 1,
    "event_type": "PURCHASE",
    "quantity": 100,
    "event_id": "evt-uuid-123"
}
```

| Event Type | Effect | Notes |
|---|---|---|
| `PURCHASE` | +quantity | Stock received |
| `SALE` | -quantity | Oversell protected |
| `DAMAGE` | -quantity | Oversell protected |
| `RETURN` | +quantity | Customer return |
| `ADJUSTMENT` | ±quantity | Manual correction |

```http
GET /api/inventory/{product_id}       # current stock level
GET /api/inventory/events/{product_id} # full event history
```

### Bulk / Generic Ingestion

Two generic, platform-agnostic paths for real sales data — not tied to a
specific POS/e-commerce vendor — beyond posting one event at a time:

```http
POST /api/inventory/events/bulk
Content-Type: multipart/form-data

file: events.csv   # columns: sku, event_type, quantity, event_id
```

```http
POST /api/webhooks/ingest
X-Webhook-Signature: <hex HMAC-SHA256 of the raw body, keyed by WEBHOOK_SECRET>
{
    "source": "generic",
    "events": [
        { "sku": "WGT-001", "event_type": "SALE", "quantity": 3, "external_id": "txn_123" }
    ]
}
```

Both share one ingestion core and report per-row results — one bad row
doesn't fail the whole batch:

```json
{
    "rows_processed": 2,
    "rows_succeeded": 1,
    "rows_failed": 1,
    "results": [
        { "row_number": 1, "event_id": "...", "status": "success", "error": null },
        { "row_number": 2, "event_id": "...", "status": "failed", "error": "..." }
    ]
}
```

The webhook's `event_id` is derived as `"{source}:{external_id}"`. It's
signed separately from `/api`'s bearer-token auth (see
[Environment Variables](#environment-variables)) — a different trust
boundary, since it's meant for an external system to call directly.

---

## Testing

```bash
make test          # unit + integration tests
make test-e2e      # end-to-end (requires Docker)
make test-all      # everything

pytest --cov=app tests/  # with coverage
```

| Test file | Coverage |
|---|---|
| `test_products.py` | Product creation, SKU uniqueness |
| `test_inventory.py` | Core inventory flow, oversell protection (Postgres-only) |
| `test_inventory_validation.py` | Input validation per event type |
| `test_idempotency.py` | Duplicate event handling |
| `test_auth.py` | API-key auth: exempt `/health`, missing/wrong/correct key, auth-disabled mode |
| `test_forecast.py` | Forecast/restock endpoints, including 404s on nonexistent products |
| `test_metrics.py` | `/metrics` exposition, request counters/latency, `X-Request-ID` header |
| `test_ingestion.py` | Shared ingestion core + CSV bulk import: partial success, idempotency, malformed rows |
| `test_webhook.py` | Webhook signature verification, per-source event_id namespacing, partial failure |
| `test_edge_cases.py` | RETURN/DAMAGE/ADJUSTMENT event types, quantity validation, stock going negative |
| `test_export.py` | Data lake export: full + incremental, partition structure, schema, empty-export no-crash |
| `test_warehouse.py` | dbt dimension/fact table builds, `_safe_path()` traversal/symlink guard |
| `test_replay.py` | Rebuilding `InventoryState` from the event log |
| `test_pagination.py` | `limit`/`offset` on list endpoints |
| `test_dashboard.py` | Streamlit dashboard renders and shows inventory metrics (AppTest) |
| `test_security_headers.py` | Response headers: nosniff/X-Frame-Options/Referrer-Policy, conditional HSTS |
| `test_db_isolation.py` | Test DB isolation between test cases |

---

## Makefile Reference

```bash
make up           # start services
make down         # stop services
make reset        # full reset (destroys data)
make migrate      # apply Alembic migrations
make logs         # tail API logs
make shell        # shell into API container
make export       # export events → Parquet data lake
make warehouse    # build DuckDB warehouse
make dbt-run      # run dbt models
make dbt-test     # run dbt data quality tests
make features     # build feature store
make train-deps   # install mlflow-skinny (one-off, for the model registry)
make train        # train Prophet models, logged to the MLflow registry
make test         # run tests
make test-e2e     # run e2e tests
make lint         # ruff check .
make format       # ruff format .
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/ims` | PostgreSQL connection |
| `TEST_DATABASE_URL` | unset | Postgres URL for integration tests; unset falls back to in-memory SQLite (postgres-marked tests skip) |
| `DB_POOL_SIZE` | `5` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Extra connections allowed above pool size under load |
| `CORS_ORIGINS` | `http://localhost:8501` | Comma-separated list of allowed CORS origins |
| `JWT_SECRET` | unset | Signs/verifies JWTs issued by `POST /api/auth/login`; unset falls back to a fixed, publicly-known dev secret (local dev only — see [SECURITY.md](SECURITY.md)) |
| `WEBHOOK_SECRET` | unset | Shared secret for verifying `POST /api/webhooks/ingest` signatures (`X-Webhook-Signature`); unset disables verification (local dev only) |
| `DATA_LAKE_ROOT` | `./data_lake` | Parquet data lake root |
| `WAREHOUSE_ROOT` | `./warehouse` | DuckDB warehouse root |
| `FEATURE_STORE_PATH` | `./feature_store` | Feature store output path |
| `MODELS_DIR` | `./models` | Trained Prophet model output path |
| `MLFLOW_TRACKING_URI` | `sqlite:///./mlflow.db` | MLflow model registry backend, used by `make train` only — see [docs/model-registry.md](docs/model-registry.md) |
| `MLFLOW_EXPERIMENT_NAME` | `prophet-demand-forecasting` | MLflow experiment name for training runs |
| `WAREHOUSE_START_DATE` / `WAREHOUSE_END_DATE` | `2020-01-01` / `2030-12-31` | Date range for the generated `dim_dates` warehouse table |
| `PYTHONPATH` | `/app` | Python module path (set inside the Docker container) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `postgres` / unset / `ims` | `docker-compose.prod.yml` only — compose-level substitution to build `DATABASE_URL`, see [self-hosted deployment](docs/deployment/self-hosted.md) |
| `DOMAIN` | unset | `docker-compose.caddy.yml` only — your domain, for automatic HTTPS |
| `PROMETHEUS_MULTIPROC_DIR` | unset | Merges `/metrics` across Gunicorn workers in production — see [docs/observability.md](docs/observability.md) |

Copy `.env.example` to `.env` and adjust as needed.

---

## Roadmap

| Epoch | Focus | Status |
|---|---|---|
| 0 | Foundations | ✅ Complete |
| 1 | Event-Driven Backend (CQRS + event sourcing) | ✅ Complete |
| 2 | Batch Data Pipeline (Parquet data lake) | ✅ Complete |
| 3 | Data Warehouse (DuckDB + dbt) | ✅ Complete |
| 4 | Feature Engineering | ✅ Complete |
| 5 | ML Platform (Prophet forecasting) | ✅ Complete |
| 6 | Streamlit Dashboard | ✅ Complete |
| 7 | Production Hardening + Deployment (self-hosted + AWS) | In Progress |

---

## Contributing

Contributions and issue reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
for local setup, running tests, and PR conventions. Please review
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) as well. Security issues should go
through [SECURITY.md](SECURITY.md) rather than a public issue.

## License

[MIT](LICENSE)

## Author

**Sinan Demir** — Computer Science @ University of Texas at Dallas
