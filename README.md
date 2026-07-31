# IMS — Inventory Management System

[![CI](https://github.com/sinan-can-demir/ims/actions/workflows/ci.yml/badge.svg)](https://github.com/sinan-can-demir/ims/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An event-driven inventory platform with a full analytics pipeline and ML-powered demand forecasting. Started as a learning project covering data engineering, backend systems, and machine learning — it's since grown into a portfolio-scale build with real production hardening (auth, audit logging, rate limiting, a verified self-hosted deployment) and a shipped multi-tenancy rework.

**Stack:** FastAPI · PostgreSQL · dbt · DuckDB · Prophet · Streamlit · Docker

> **Project status:** actively developed portfolio project, not a hardened production system.
> Auth is per-user JWT bearer tokens with two roles (admin/member) — see [SECURITY.md](SECURITY.md) for the current auth model. Path A (restaurant deployment), the self-hosted deployment/S3 hardening work (`#74`, `#22`), and Epoch 10 (multi-tenancy, Path B) are all shipped — see [ROADMAP.md](ROADMAP.md) for what's next (Path B's remaining epochs, 11-15, are scoped but not started) and [docs/multi-tenancy.md](docs/multi-tenancy.md) for the multi-tenancy architecture. See [Deployment](#deployment) below for how to run it yourself.

---

## What Works Now

- [x] Event-sourced inventory core — append-only `InventoryEvent` log +
      `InventoryState` projection, idempotent writes (`event_id`), oversell
      protection
- [x] Product + inventory REST API (FastAPI/Postgres), per-user JWT bearer
      auth (two roles: admin/member — see [SECURITY.md](SECURITY.md))
- [x] Recipes/BOM — a dish consumes its ingredients in fixed quantities when
      sold, atomically with the sale (`POST /api/recipes`)
- [x] Real Purchase Order object (draft/submit/receive) — turns a
      forecast + current stock into an actual order, not just a restock
      number on the dashboard; receiving creates real `PURCHASE` events
- [x] Bulk CSV import (`POST /api/inventory/events/bulk`) — per-row partial
      success
- [x] Generic HMAC-signed webhook ingestion, per-org secret
      (`POST /api/webhooks/{organization_id}/ingest`)
- [x] Full analytics pipeline: Parquet data lake → DuckDB warehouse → dbt
      models + data quality tests
- [x] Prophet demand forecasting per product, tracked in an MLflow model
      registry — backtested for day-of-week-heavy demand (e.g. restaurant
      weekday/weekend spikes); requires 14+ days of history so
      `weekly_seasonality` has seen the weekly cycle repeat at least once
- [x] Multi-page Streamlit dashboard — Product Detail (live inventory,
      configurable-horizon demand forecast, safety-stock/days-of-stock
      KPIs, filterable/paginated event history), Fleet Overview
      (portfolio-wide KPIs, urgency filtering, click-through to Product
      Detail), Recipes/BOM, Purchase Orders, and an admin/ops panel
      (replay + export), themed via `.streamlit/config.toml`
- [x] Prometheus metrics + structured JSON request logging
      (`/metrics`, `X-Request-ID`)
- [x] CI on every push/PR — lint, full test suite (incl. Postgres-only
      tests), Docker build, dependency/secret/image vulnerability scanning
      (Dependabot + gitleaks + pip-audit + trivy), and a dedicated pipeline
      job exercising export → warehouse → dbt against a real Postgres
- [x] Self-hosted deployment path (Docker Compose + optional Caddy HTTPS) —
      verified against a real running deployment, including public
      reachability
- [x] S3-compatible object storage for the data pipeline — MinIO by default
      for self-hosted (runs alongside the stack, zero extra cost), real AWS
      S3 for the AWS path; local disk stays the default either way. See
      [docs/deployment/self-hosted.md](docs/deployment/self-hosted.md#s3--minio-storage-optional)
- [x] `scripts/backup.sh` / `scripts/restore.sh` — one archive covering
      both Postgres and the local pipeline artifacts (data lake, feature
      store, warehouse, models); see
      [docs/deployment/self-hosted.md](docs/deployment/self-hosted.md#backups)
- [x] Operator CLI (`scripts/ims.py setup|start|stop|status|backup|restore`)
      — `setup` doubles as the first-run wizard, no separate one needed
- [x] Dashboard deployed alongside the API in the self-hosted stack, gated
      behind Caddy basic auth (the dashboard has no auth of its own)
- [x] Security response headers (X-Frame-Options, X-Content-Type-Options,
      Referrer-Policy, conditional HSTS)
- [x] Rate limiting on `/api` routes (slowapi, keyed by client IP — trusting
      `X-Forwarded-For` only from a private-address proxy peer, so a shared
      Caddy/ALB in front doesn't collapse every real client into one bucket)
      — see [SECURITY.md](SECURITY.md) for a known compatibility limitation
      with newer FastAPI versions
- [x] Size caps on both generic ingestion paths (10MB/50k-row CSV bulk
      import, 1000-item webhook payload) — see [SECURITY.md](SECURITY.md#ingestion-size-limits)
- [x] Multi-tenancy — shared schema, `organization_id` on every tenant
      table, composite FKs making cross-org references structurally
      impossible at the DB level; self-hosted deployments stay
      single-org by default. See [docs/multi-tenancy.md](docs/multi-tenancy.md)

## Recently Shipped

**Path A — getting one real restaurant running this daily:** recipes/BOM
(dishes consume ingredients in fixed quantities), a `WASTE` event type, a
real `PurchaseOrder` object, day-of-week-aware forecasting, a CLI wrapper
(`ims start`/`setup`/`backup`), and a backup routine. See
[ROADMAP.md](ROADMAP.md)'s "Path A" section for the full list.

**Dashboard UX overhaul (Epoch 7.1):** multi-page navigation
(`st.navigation()`/`st.Page()`, replacing the old single-page layout), a
portfolio-wide **Fleet Overview** page (KPIs across every product, urgency
filtering, click-through to Product Detail), Product Detail enhancements
(forecast horizon slider up to 90 days, safety-stock/days-of-stock-remaining
KPI tiles, event-type filter + pagination on the event history table), and
a `.streamlit/config.toml` theming pass.

**Deployment verification + S3-compatible storage:** `#74` — the
self-hosted `docker-compose.prod.yml` path fully verified against a real
running deployment (real secrets, real migrations, restart/crash-recovery
semantics, backup/restore round-trip), plus a real fixed data-loss bug
(pipeline directories now persist across redeploys) and demonstrated public
reachability. `#22` — the data pipeline (data lake, warehouse, feature
store, trained models) migrated to a pluggable local-or-S3 storage layer,
with MinIO as the zero-cost self-hosted default; local disk stays the
out-of-the-box default either way.

**Multi-tenancy (Epoch 10, Path B):** shipped as 16 sequential PRs
(GitHub milestone "Epoch 10 — Multi-Tenancy"), deliberately ahead of any
real multi-tenant demand signal, for portfolio/learning value. Shared
schema + `organization_id` on every tenant table, composite FKs making
cross-org references structurally impossible at the DB level (not just
checked in code), explicit `organization_id` parameter threading through
every service/route (never a JWT claim or ambient context), per-org
webhook secrets, and the full analytics pipeline (export, warehouse,
dbt, feature store, model registry) partitioned per org. Along the way
this also fixed a real live bug (`rebuild_inventory_state()` used to
wipe every org's inventory projection, not just the caller's) and closed
several real IDOR gaps (bare id-only lookups with no ownership check).
Self-hosted deployments are unaffected by any of this — they stay
single-org by default (`ALLOW_MULTIPLE_ORGS=false`), see
[docs/multi-tenancy.md](docs/multi-tenancy.md) for the full architecture
writeup and what's deliberately still deferred (Postgres RLS as a
second DB-enforced isolation layer).

## Deferred

Deferred until there's real signal that more than one business wants
this (general small/mid-business audience — see
[ROADMAP.md](ROADMAP.md) Epochs 11-15):

- [ ] Real S3 + Terraform/IAM for the AWS deployment path, and a CI test
      matrix covering both local and S3 storage (`#130` — split off `#22`,
      since the AWS path isn't in active use)
- [ ] Deploy the dashboard on AWS (ECS, reading the feature store from S3)
- [ ] Apply the AWS Terraform — ECS/RDS/ALB infra is written, not yet running
- [ ] Real integrations (Shopify/QuickBooks/etc.), order management,
      front-office features

See [ROADMAP.md](ROADMAP.md) for the full backlog.

---

## What it does

- Tracks inventory changes as an **immutable event log** (event sourcing + CQRS)
- Exports events to a **Parquet data lake**, transforms them in a **DuckDB warehouse** via dbt
- Trains a **Prophet forecasting model** per product on historical demand
- Serves a **Streamlit dashboard** with live inventory levels, event history, and 30-day demand forecasts

![Dashboard](docs/images/dashboard.png)

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
ims/
├── app/                    # FastAPI application
│   ├── api/                # Route handlers (products, inventory)
│   ├── core/               # storage.py (local/S3 abstraction), auth, logging
│   ├── models/             # SQLAlchemy models
│   ├── schemas/            # Pydantic schemas
│   ├── scripts/            # export/warehouse/feature/train pipeline entry points
│   └── services/           # Business logic
├── migrations/             # Alembic migrations
├── tests/                  # Unit, integration, and e2e tests
├── data_lake/              # Parquet event snapshots (or an s3:// URI — see below)
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
├── docker-compose.minio.yml      # optional local MinIO for testing S3 storage (overlay)
├── docs/deployment/        # self-hosted deployment guide
├── docs/model-registry.md  # MLflow setup, promotion/rollback
├── docs/multi-tenancy.md   # org isolation architecture — what's enforced where
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

**Fastest path:** `python scripts/ims.py setup` sequences the steps below
(start services, wait for the API to be healthy, create your first
account if none exists) into one command — see
[Operator CLI](#operator-cli-scriptsimspy) below. Or do it manually:

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
{ "name": "Widget A", "sku": "WGT-001", "unit": "each" }

GET /api/products   # list every product
```

`unit` is an optional free-text display label (e.g. `"g"`, `"ml"`, `"each"`)
— not a unit-conversion system. Recipe quantities (below) are always
expressed in the component product's own unit.

### Recipes / BOM

Defines what a dish (a "finished product") consumes when it's sold — a
restaurant-shaped Bill of Materials, one level deep (components are raw
ingredients, not themselves dishes with their own recipe):

```http
POST /api/recipes
{ "finished_product_id": 1, "component_product_id": 2, "quantity": 1 }

GET /api/recipes/{finished_product_id}   # list a dish's ingredients
PATCH /api/recipes/{recipe_item_id}      # { "quantity": 3 }
DELETE /api/recipes/{recipe_item_id}
```

Selling a dish (`POST /api/inventory/events` with `event_type: "SALE"`)
automatically decrements every ingredient's stock by `quantity × units
sold`, atomically with the dish's own sale — if any ingredient can't cover
it, the whole sale (dish + ingredients) is rejected and nothing is
partially applied. Cascaded ingredient consumption is recorded as its own
`SALE` event per ingredient, so per-ingredient demand forecasting/restock
picks up recipe-driven demand automatically.

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
| `WASTE` | -quantity | Oversell protected; tracked distinctly from DAMAGE (spoilage/waste, not breakage) |

```http
GET /api/inventory/{product_id}       # current stock level
GET /api/inventory/events/{product_id} # full event history
```

### Suppliers & Purchase Orders

Turns a forecast + current stock into an actual, persisted order, not just
a restock number on the dashboard — draft → submitted → received, where
receiving a PO creates real `PURCHASE` inventory events per line:

```http
POST /api/suppliers
{ "name": "Acme Foods", "contact_email": "orders@acme.example" }

POST /api/purchase-orders
{ "supplier_id": 1, "lines": [{ "product_id": 2, "quantity": 50, "unit_cost": 1.25 }] }

POST /api/purchase-orders/{id}/lines         # add a line (draft only)
PATCH /api/purchase-orders/lines/{line_id}   # edit a line (draft only)
DELETE /api/purchase-orders/lines/{line_id}  # remove a line (draft only)

POST /api/purchase-orders/{id}/submit    # draft -> submitted (needs >=1 line)
POST /api/purchase-orders/{id}/receive   # submitted -> received, creates PURCHASE events

POST /api/purchase-orders/generate/{product_id}?supplier_id=1
# pre-fills a draft PO's single line from that product's current
# restock recommendation (see GET /api/forecast/restock/{product_id})
```

Receiving is retry-safe: each line's inventory event uses a deterministic
`event_id` (`po-{id}-line-{id}`), so retrying a receive that failed
partway through re-applies only the lines that didn't already succeed,
never double-counting one that did.

### Bulk / Generic Ingestion

Two generic, platform-agnostic paths for real sales data — not tied to a
specific POS/e-commerce vendor — beyond posting one event at a time:

```http
POST /api/inventory/events/bulk
Content-Type: multipart/form-data

file: events.csv   # columns: sku, event_type, quantity, event_id
```

```http
POST /api/webhooks/{organization_id}/ingest
X-Webhook-Signature: <hex HMAC-SHA256 of the raw body, keyed by that org's own webhook_secret>
{
    "source": "generic",
    "events": [
        { "sku": "WGT-001", "event_type": "SALE", "quantity": 3, "external_id": "txn_123" }
    ]
}
```

The signing secret is per-org (`organizations.webhook_secret`), not a
single global secret — a NULL secret disables signature verification for
that org only (local dev only), same "unset = disabled" shape the old
global `WEBHOOK_SECRET` env var had. See [SECURITY.md](SECURITY.md).

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
| `test_forecast.py` | Forecast/restock endpoints (404s on nonexistent products), and a real (non-mocked) backtest proving `weekly_seasonality=True` beats it off on day-of-week-shaped demand, plus the 14-day minimum-training-data guard |
| `test_metrics.py` | `/metrics` exposition, request counters/latency, `X-Request-ID` header |
| `test_ingestion.py` | Shared ingestion core + CSV bulk import: partial success, idempotency, malformed rows |
| `test_webhook.py` | Webhook signature verification, per-source event_id namespacing, partial failure |
| `test_edge_cases.py` | RETURN/DAMAGE/WASTE/ADJUSTMENT event types, quantity validation, stock going negative |
| `test_export.py` | Data lake export: full + incremental, partition structure, schema, empty-export no-crash |
| `test_warehouse.py` | dbt dimension/fact table builds, `_safe_path()` traversal/symlink guard |
| `test_replay.py` | Rebuilding `InventoryState` from the event log |
| `test_pagination.py` | `limit`/`offset` on list endpoints |
| `test_dashboard.py` | Streamlit dashboard renders and shows inventory metrics (AppTest), multi-page routing via `st.navigation()`; also covers the Recipes page (`dashboard/views/recipes.py`) and the Purchase Orders page (`dashboard/views/purchase_orders.py`) |
| `test_purchase_orders.py` | Supplier/PO CRUD, full draft→submit→receive lifecycle, state-transition guards, generate-from-forecast, retry-safety after a partial receive failure |
| `test_security_headers.py` | Response headers: nosniff/X-Frame-Options/Referrer-Policy, conditional HSTS |
| `test_db_isolation.py` | Test DB isolation between test cases |
| `test_recipes.py` | Recipe/BOM CRUD, sale-triggered ingredient cascade, cascade atomicity, idempotent replay |
| `test_ims_cli.py` | `scripts/ims.py` argparse wiring, health-check polling, backup/restore wrapper behavior (subprocess/urllib mocked — real end-to-end run verified manually) |

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

## Operator CLI (`scripts/ims.py`)

A thin wrapper over the Makefile/docker compose workflow above — plain
`python scripts/ims.py <command>`, matching every other script in
`scripts/` (no pip-installable entry point; see the file's own header
comment for why):

```bash
python scripts/ims.py setup     # first-run wizard: start services, wait for
                                 # the API to be healthy, create the first
                                 # account if none exists yet
python scripts/ims.py start     # docker compose up -d
python scripts/ims.py stop      # docker compose down
python scripts/ims.py status    # container status, API health, migration state
python scripts/ims.py backup <destination_dir>       # wraps scripts/backup.sh
python scripts/ims.py restore <backup_archive.tar.gz> # wraps scripts/restore.sh
```

`setup` is scoped to the local/self-hosted dev-quickstart flow, not a
substitute for [docs/deployment/self-hosted.md](docs/deployment/self-hosted.md)'s
production setup (domain, secrets, Caddy) — those are deployment-specific
decisions no wizard should make silently.

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
| `RATE_LIMIT` | `100/minute` | Default rate limit on `/api` routes (slowapi syntax) |
| `DATA_LAKE_ROOT` | `./data_lake` | Parquet data lake root — local path or an `s3://` URI |
| `WAREHOUSE_ROOT` | `./warehouse` | Warehouse mart/dim Parquet output — local path or an `s3://` URI |
| `WAREHOUSE_DB_PATH` | `./warehouse/ims.duckdb` | The DuckDB catalog file dbt and the feature builder both open — always local, never `s3://` (no supported way to run a writable DuckDB database on S3); separate from `WAREHOUSE_ROOT` above on purpose |
| `FEATURE_STORE_PATH` | `./feature_store` | Feature store output path — local path or an `s3://` URI |
| `MODELS_DIR` | `./models` | Trained Prophet model output path — local path or an `s3://` URI |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | unset | S3-compatible object storage credentials — only used if one of the 4 paths above is an `s3://` URI |
| `S3_ENDPOINT_URL` | unset | S3-compatible endpoint (e.g. `http://minio:9000`); leave unset for real AWS S3 |
| `S3_URL_STYLE` | unset | `path` for MinIO/most self-hosted S3-compatible servers; unset (AWS's default `vhost` style) for real AWS S3 |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | unset | MinIO's own admin credentials — `docker-compose.prod.yml`/`docker-compose.minio.yml` only, required to start the `minio` container. See [docs/deployment/self-hosted.md](docs/deployment/self-hosted.md#s3--minio-storage-optional) |
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
| 7 | Production Hardening + Deployment (self-hosted + AWS) | ✅ Complete for self-hosted — `#74` (deploy verified) and `#22` (S3 storage) both shipped. AWS-path S3/Terraform tracked separately in `#130` |
| 7.1 | Dashboard UX Overhaul — multi-page nav, Fleet Overview, Product Detail enhancements, theming | ✅ Complete |
| Path A | Restaurant deployment — recipes/BOM, `WASTE` events, real POs, forecasting tuning, CLI wrapper, backups | ✅ Complete |
| 10 | Multi-Tenancy (Path B) | ✅ Complete — shipped as 16 sequential PRs, see [docs/multi-tenancy.md](docs/multi-tenancy.md) |
| 11-15 | General small/mid-business platform (Path B) | Scoped in detail, not started — whether to start at all is an open decision |

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
