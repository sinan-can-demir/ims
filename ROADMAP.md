# IMS — Inventory Management System
Author: Sinan Demir
Last Updated: 2026-07-26

This roadmap organizes the development of IMS into **epochs**.
Each epoch unlocks the next capability. The system evolves from a simple
backend into a full data platform with ML and a dashboard.

Core principles:
- Events are the **source of truth**
- Schemas are **contracts**
- Pipelines must be **reproducible**
- ML depends on **data quality**

------------------------------------------------------------
EPOCH 0 — Foundations
------------------------------------------------------------

Goal: Create a minimal, reproducible backend environment.

- [x] Project structure
- [x] FastAPI backend
- [x] PostgreSQL database
- [x] Docker environment (with Fedora :Z volume fix)
- [x] SQLAlchemy models
- [x] Event-driven inventory schema
- [x] Inventory projection (inventory_state)
- [x] Alembic migrations setup

Milestone: Complete
- Database schema versioned with Alembic
- Tables: products, inventory_events, inventory_state, alembic_version
- Docker startup runs migrations automatically before serving

------------------------------------------------------------
EPOCH 1 — Event-Driven Backend
------------------------------------------------------------

Goal: Build a robust, production-hardened event-driven inventory system.

- [x] Add event table indexes (product_id, created_at, composite)
- [x] Enforce product_id NOT NULL in inventory_events
- [x] Add idempotency key (event_id) to inventory events
- [x] Quantity normalization per event type
- [x] Oversell protection (inventory cannot go below 0)
- [x] SELECT FOR UPDATE concurrency safety on inventory_state row
- [x] Inventory read from projection, not SUM(events)
- [x] Event writes and projection updates in single transaction
- [x] Duplicate SKU returns 409 Conflict
- [x] Pydantic v2 migration (ConfigDict, no deprecation warnings)
- [x] Structured JSON logging (app/core/logging.py)
- [x] Event replay service (rebuild_inventory_state from events)
- [x] Integration tests (pytest with SQLite StaticPool in-memory DB)
- [x] Test isolation (tables created/dropped per function fixture)
- [x] Shared test utility (tests/utils.py)
- [x] Makefile targets (up, down, reset, logs, test, test-e2e, migrate, shell)
- [x] E2E bash test script (test_scripts/test_sc.sh)
- [x] Response models and correct status codes (201 for POST)
- [x] Deterministic event ordering (ORDER BY created_at ASC, id ASC)
- [x] Pagination on event listing endpoint (limit, offset)
- [x] Edge case tests (return/damage sequence, large adjustments)
- [x] README accurate and synced with actual endpoints

Milestone: Complete

------------------------------------------------------------
EPOCH 2 — Batch Data Platform
------------------------------------------------------------

Goal: Export the event log into a partitioned data lake.

- [x] data_lake/ directory and inventory_events/ subfolder
- [x] .gitignore excludes parquet files and checkpoints.json
- [x] Export service (export_service.py)
- [x] Query events ordered by (created_at, id)
- [x] Partition by year/month/day
- [x] Write partitioned .parquet files
- [x] Incremental export using checkpoints.json
- [x] Full and incremental export modes
- [x] POST /api/inventory/export endpoint
- [x] Validation script (validate_exports.py)
- [x] CLI script (app/scripts/export_events.py)
- [x] pytest tests for export service
- [x] Handle timezone-naive datetimes from SQLite in tests
- [x] Makefile target: make export

Milestone: Complete

------------------------------------------------------------
EPOCH 3 — Data Warehouse
------------------------------------------------------------

Goal: Build an analytical layer on top of the data lake using DuckDB.

- [x] DuckDB installed and reading Parquet files
- [x] Star schema design (fact + dimensions)
- [x] dim_products built from PostgreSQL
- [x] dim_dates pre-generated for full date range
- [x] fact_inventory_events joined from data lake
- [x] Three analytical queries documented (warehouse/queries.sql)
- [x] CLI script (app/scripts/build_warehouse.py)
- [x] Makefile target: make warehouse
- [x] Warehouse tests (test_warehouse.py)
- [x] warehouse/README.md documents schema and rebuild steps

Milestone: Complete

------------------------------------------------------------
EPOCH 4 — dbt Transformations
------------------------------------------------------------

Goal: Replace hand-written Python warehouse service with dbt models.

- [x] dbt-duckdb installed and configured
- [x] dbt project initialized (warehouse/ims_warehouse/)
- [x] profiles.yml configured for DuckDB
- [x] Sources declared (sources.yml)
- [x] Staging model (stg_inventory_events.sql)
- [x] Dimension models (dim_products.sql, dim_dates.sql)
- [x] Fact model (fact_inventory_events.sql)
- [x] Schema tests (unique, not_null, relationships)
- [x] dbt docs generated
- [x] Makefile targets: make dbt-run, make dbt-test, make dbt-docs
- [x] warehouse_service.py deprecated with clear comment

Milestone: Complete

------------------------------------------------------------
EPOCH 5 — ML Platform
------------------------------------------------------------

Goal: Enable demand forecasting and restock recommendations.

- [x] Feature engineering service (feature_service.py)
- [x] daily_sales feature table (product_id, date, units_sold, rolling_avg_7d)
- [x] Prophet model training per product (forecast_service.py)
- [x] Model persistence (models/prophet_{product_id}.pkl)
- [x] Forecast API endpoint (GET /api/forecast/{product_id})
- [x] Restock recommendation service (restock_service.py)
- [x] Restock API endpoint (GET /api/restock/{product_id})
- [x] Urgency classification (OK / LOW / URGENT / STOCKOUT)
- [x] Pydantic schemas for forecast and restock responses
- [x] CLI scripts: make features, make train
- [x] Seed data script (scripts/seed_data.py)
- [x] Synthetic feature generator (scripts/generate_synthetic_features.py)
- [x] Forecast and restock tests (test_forecast.py)

Milestone: Complete

------------------------------------------------------------
EPOCH 6 — Application Layer (Dashboard)
------------------------------------------------------------

Goal: Build an interactive inventory dashboard with Streamlit.

- [x] Streamlit installed and configured
- [x] dashboard/app.py with full layout
- [x] Product selector (sidebar dropdown)
- [x] Inventory metrics (current stock, projected demand, recommended order)
- [x] Restock alert with urgency color coding
- [x] 7-day demand forecast chart with confidence band (Plotly)
- [x] Recent inventory events table
- [x] Cached data loaders (@st.cache_data with TTL)
- [x] Loading spinners and empty state handling
- [x] Makefile target: make dashboard

Milestone: Complete

------------------------------------------------------------
EPOCH 7 — Production Hardening & AWS Deployment (In Progress)
------------------------------------------------------------

Goal: Make the system production-grade and deploy it to AWS.  

Phase 1 — Quick wins (no architecture changes)  
- [x] Pin all dependency versions in requirements.txt  
- [x] Add /health endpoint to FastAPI app (required by AWS ALB/ECS)  
- [x] Add CORS middleware to FastAPI app (origins via CORS_ORIGINS env var)  
- [x] Add .env.example documenting all required environment variables  
- [x] Fix docker-compose: add Postgres healthcheck, remove fragile sleep 3  
- [x] Tune SQLAlchemy connection pool for cloud (pool_pre_ping, pool_size, max_overflow)  

Phase 2 — Security hardening  
- [x] Add API authentication (API key header) — app/core/auth.py, X-API-Key,
      wired via Depends on every router; no-op (with a loud startup warning)
      if API_KEY is unset, by design for local dev — see SECURITY.md.
      **Superseded 2026-07-25 by per-user JWT auth — API_KEY was removed
      entirely, see Hardening Phase C below.**  
- [x] Add non-root USER to Dockerfile — appuser (uid 1000, matches the default
      first-user uid on most Linux distros so the dev bind-mount stays
      writable); curl also added, since HEALTHCHECK depended on it but it
      wasn't present in the slim base image  
- [x] Stop leaking internal error details (replace str(e) in forecast.py 500
      responses) — generic exceptions now return a fixed "Internal server
      error" message; only FileNotFoundError still surfaces detail (404, not
      sensitive)  
- [x] Remove hardcoded credentials from docker-compose.yml and database.py
      defaults — resolved via docker-compose.prod.yml, which fails loudly on
      a missing POSTGRES_PASSWORD for real deployments. The base
      docker-compose.yml / database.py fallback (postgres/postgres) is kept
      intentionally as a local-dev-only default, same pattern as API_KEY —
      not used by either deployment path (self-hosted prod overlay or AWS)  

Phase 3 — App hardening  
- [x] Raise domain exceptions in service layer instead of HTTPException —
      app/core/exceptions.py (DomainError base + ProductNotFoundError,
      DuplicateSKUError, InvalidEventError, InsufficientInventoryError), a
      single @app.exception_handler(DomainError) in main.py converts them to
      HTTP responses. app/services/ now has zero FastAPI imports  
- [x] Run Uvicorn with multiple workers in production (Gunicorn +
      UvicornWorker) — docker-compose.prod.yml and infra/ecs.tf both run
      `gunicorn -k uvicorn.workers.UvicornWorker`; worker count is
      WEB_CONCURRENCY (default 4) for self-hosted and the gunicorn_workers
      Terraform variable (default 2, conservative given the cheapest Fargate
      tier's 512MB) for AWS. The base docker-compose.yml dev command stays
      single-worker plain Uvicorn for easier debugging  
- [x] Improve Dockerfile: multi-stage build, proper .dockerignore (non-root
      user already done, see Phase 2) — builder stage installs deps into
      /opt/venv, final stage only copies that + app code, no pip cache/apt
      lists/build layer. .dockerignore was missing .venv/ and .git/, which
      were silently adding ~1GB of dead weight to every build (COPY . .
      copied them wholesale) — final image dropped from 4.44GB to 3.22GB  

Phase 4 — Testing  
- [x] Run integration tests against a real Postgres instead of SQLite —
      ci.yml's test job runs the full suite (incl. @pytest.mark.postgres
      tests like SELECT FOR UPDATE oversell protection) against a real
      Postgres service container  
- [x] Add CI/CD via GitHub Actions — ci.yml runs lint/test/docker-build on
      every push and PR to main  

Phase 5 — Deployment (self-hosted + AWS)  
Two paths, not one — being open-source, the default should be the cheapest
and most portable option, with AWS available for teams that already run
there. See README.md's "Deployment" section.

Self-hosted (default, docs/deployment/self-hosted.md):  
- [x] docker-compose.prod.yml — prod hardening overlay (no dev bind-mount,
      no exposed DB port, fail-loud on missing secrets)  
- [x] docker-compose.caddy.yml — optional automatic HTTPS via Caddy  
- [x] Self-hosted deployment guide  
- [x] Move data lake from local filesystem to object storage (#22 — shipped
      2026-07-28, PRs #121-129: storage abstraction (app/core/storage.py),
      MinIO as the self-hosted default, all 4 pipeline roots + dbt/DuckDB
      wired for S3, backup/reset safety nets. AWS S3 Terraform/IAM + a CI
      local+S3 test matrix split into a follow-up issue, since the AWS path
      isn't in active use — see Phase C below)  
- [x] Deploy dashboard alongside the API in the self-hosted stack — `dashboard`
      compose service; its port stays unpublished until the Caddy overlay
      fronts it with basic_auth on a dedicated port (#32). Now also has its
      own per-user sign-in (#85, dashboard/auth.py) that coexists with
      basic_auth rather than replacing it — network perimeter vs. per-user
      attribution inside the app, see SECURITY.md  

AWS (enterprise, infra/README.md):  
- [~] Configure AWS infrastructure (ECS Fargate, RDS PostgreSQL, ALB) — Terraform written (infra/), not yet applied  
- [~] Store secrets in AWS Secrets Manager, inject as environment variables — wired in Terraform, not yet applied  
- [~] Wire CloudWatch Logs — wired in Terraform, not yet applied  
- [ ] Move data lake from local filesystem to S3 (self-hosted/MinIO path
      shipped via #22; the real-S3/Terraform/IAM half of this for the AWS
      path is split into #130, not yet started)  
- [ ] Deploy dashboard (Streamlit on ECS, read feature store from S3)  
- [ ] Set up domain + HTTPS via ACM + ALB  
- [x] Harden RDS Terraform defaults — backups, deletion_protection, multi-AZ
      (#20) — see the Hardening Phase B checklist below for detail  

Milestone: App deployable via either path with real auth, secrets management, and CI/CD  

------------------------------------------------------------
EPOCH 7 — Phase 6 — Observability, Auth Upgrade & Ops Maturity (In Progress)
------------------------------------------------------------

Goal: Close out the remaining production-hardening backlog. Originally filed
as issues #16–23 under the `production-hardening` milestone; GitHub has
since reorganized this backlog (plus a second full audit pass, #27–33) into
three milestones by risk/effort — Hardening Phase A (Quick Wins), Phase B
(Moderate Risk), Phase C (Needs Scoping). Order below follows each issue's
`status:*` label (ready before blocked) and real dependencies, not filing
order — see the issue tracker for current status, this list is a
point-in-time snapshot.

- [x] Add Prometheus metrics and structured JSON logging (#19) — `/metrics`
      endpoint (app/core/metrics.py) with request counters + latency
      histogram, multiprocess-safe for Gunicorn's multi-worker production
      mode (gunicorn.conf.py); RequestLoggingMiddleware logs a
      `request_completed` JSON event per request with a correlation ID,
      also returned as `X-Request-ID`. See docs/observability.md  
- [x] Add model registry (MLflow) and log Prophet artifacts (#16 — help-wanted) —
      mlflow-skinny (requirements-train.txt, not part of the API image),
      SQLite-backed registry (mlflow.db + mlruns/, both gitignored). `make
      train` registers each product's model (prophet_{product_id}) and logs
      params + in-sample MAE/MAPE; serving (forecast()/load_model()) is
      unchanged — still reads models/*.pkl directly. Promotion/rollback via
      MLflow's alias API documented in docs/model-registry.md  

Hardening Phase A — Quick Wins: **complete, 7/7 (2026-07-24)**  
- [x] Bound the `days` query param on GET /api/forecast/{product_id} (#30)  
- [x] Add security response headers middleware (#27) — X-Content-Type-Options,
      X-Frame-Options, and Referrer-Policy set on every response;
      Strict-Transport-Security only when X-Forwarded-Proto is https, since
      uvicorn itself always sees plain HTTP behind Caddy/ALB
      (app/core/security_headers.py)  
- [x] Add rate limiting to /api routes (#28) — see SECURITY.md; **note the
      known incompatibility filed as #66, Phase B below**  
- [x] Add security-focused lint rules to CI — ruff `S` ruleset (#29)  
- [x] Misc hardening cleanup — .dockerignore gaps, pin base image, add a
      replay-endpoint auth test (#31)  
- [x] CI: run dbt and integration tests against Postgres in CI (#18) — new
      `pipeline` CI job: migrate, seed, export, build warehouse, `dbt run`,
      `dbt test`. Fixing this surfaced real, previously-uncaught bugs: no
      `profiles.yml` had ever been committed (dbt only ever ran on the
      original dev's machine), three dbt files hardcoded that dev's personal
      absolute path as their `env_var` fallback, and
      `models/marts/schema.yml` declared `fact_inventory_events` twice —
      dbt rejects duplicate resource names outright, never caught because
      dbt had never actually run anywhere but one machine  
- [x] Add dependency & secret scanning to CI — Dependabot, trivy/pip-audit (#17)
      — new `scan` CI job (gitleaks, pip-audit, trivy image scan) plus
      `.github/dependabot.yml` (pip/docker/github-actions, weekly). First
      Dependabot run opened 13 PRs at once (one-time backlog flood); one of
      them surfaced #66 below via a real CI test failure  

Hardening Phase B — Moderate Risk:  
- [x] Make migrations a one-off job, remove inline alembic from startup (#21 —
      inline migrations racing across multiple Gunicorn workers, introduced
      by the Phase 3 multi-worker change, was a real correctness risk) —
      done for both self-hosted (#38) and AWS (#39)  
- [x] Add authentication in front of the Streamlit dashboard (#32) — see the
      Phase 5 self-hosted checklist above  
- [x] Validate DuckDB glob paths in warehouse_service.py instead of raw
      f-string interpolation (#33) — `_safe_path()` now requires the
      resolved path to actually stay within its expected root, not just
      reject shell metacharacters; also catches symlink escapes  
- [x] Harden RDS Terraform defaults — backups, deletion_protection, multi-AZ
      (#20) — `db_multi_az`/`db_backup_retention_period`/
      `db_deletion_protection` variables, all hardened by default
      (`infra/variables.tf`, `infra/rds.tf`); not yet `apply`'d against real
      AWS (no live infra to test against), verified via `terraform validate`
      + `fmt` per this repo's established bar for untested infra changes  
- [x] Fix `slowapi` silently no-op'ing rate limiting on fastapi>=0.140.0 (#66
      — FastAPI restructured `include_router()` internals into a private
      `_IncludedRouter` wrapper that slowapi's route lookup doesn't
      recognize, so rate limiting stopped applying to every `/api` route
      with no error. Fixed by enforcing the limit via a `Depends()` instead
      of `SlowAPIMiddleware` (#79), which also unblocked the fastapi 0.140.0
      bump. See SECURITY.md)  

Hardening Phase C — Needs Scoping:  
- [x] Replace shared API key auth with per-user JWT-based authentication
      (#23, closed 2026-07-25) — scoped bigger than the original
      "JWT/OIDC swap" framing once real per-event attribution and a
      lightweight audit trail turned out to be natural, cheap additions on
      top of real user identity. Shipped as 6 sequential PRs: users table +
      bcrypt password hashing (#78), JWT login endpoint +
      `require_current_user` (#86), `API_KEY` removed entirely and every
      `/api` route cut over to bearer tokens (#87),
      `InventoryEvent.created_by_id` per-event attribution (#88),
      `audit_log` table for replay/export/login_failed (#89), and the
      dashboard sign-in gate (#90). No self-service registration —
      accounts are CLI-only via `scripts/create_user.py`. See SECURITY.md
      for the current auth model.  
- [x] Move data lake to S3, update export/dbt to use S3 (#22 — shipped
      2026-07-28, PRs #121-129, ~2 days across a 9-PR arc, not the
      original 1-3 day estimate: new `app/core/storage.py` abstraction,
      MinIO as the self-hosted default (`docker-compose.prod.yml`/
      `docker-compose.minio.yml`), every pipeline root (export, warehouse,
      dbt/DuckDB `httpfs`, feature store, models) migrated and verified
      live against real MinIO, backup/reset S3-mode safety nets. The
      DuckDB catalog file stays local always (new `WAREHOUSE_DB_PATH`,
      decoupled from `WAREHOUSE_ROOT` — no supported way to run a
      writable DuckDB database on S3). Real S3 + Terraform + IAM for the
      AWS path, and a CI local+S3 test matrix, split into #130 since the
      AWS path isn't in active use.)  

Milestone: Hardening Phase A complete. Phase B complete — #20 (RDS
Terraform hardening) shipped as #97. Phase C complete — the JWT/user-
accounts arc (#23) shipped in full, #22 (S3 data lake) shipped for the
self-hosted path. #130 (AWS S3 Terraform + CI matrix) tracks the
remaining AWS-path piece, not yet started. See Phase D below for a
second, later audit pass. See the issue tracker for live status.  

Hardening Phase D — Fresh Pre-Deployment Security Audit (2026-07-26):
found ahead of real deployment (#74, "Ship It"), not part of the original
Phase A-C backlog.  
- [x] Trust the real client IP for rate limiting instead of the reverse
      proxy's (#98, merged) — `rate_limit_key()` (`app/core/rate_limit.py`)
      keyed on `request.client.host`, which in every documented deployment
      path is always Caddy's or the ALB's address, not the real client's —
      every user behind one proxy shared a single rate-limit bucket,
      silently defeating brute-force protection on
      `POST /api/auth/login`. Now trusts `X-Forwarded-For`'s leftmost entry
      only when the immediate TCP peer is itself a private address (i.e.
      it's our own proxy) — see SECURITY.md's "Rate limiting" section.  
- [x] Cap both generic ingestion paths (#98, merged, same PR) — 10MB/50k-row
      cap on `POST /api/inventory/events/bulk` (previously read an
      unbounded CSV fully into memory before validation), `max_length=1000`
      on `POST /api/webhooks/ingest`'s `events` list (rate-limit-exempt by
      design, so schema validation was the only available bound) — see
      SECURITY.md's "Ingestion size limits" section.  
- [x] Add DB-level tamper protection to `audit_log` (#99, PR #107) — a
      Postgres trigger rejects `UPDATE`/`DELETE` on the table regardless
      of role, so immutability no longer holds only by code convention
      (`audit_service.log_action` never updating/deleting).  

------------------------------------------------------------
EPOCH 7.1 — Dashboard UX Overhaul
------------------------------------------------------------

Goal: Epoch 6 shipped a complete, working single-page dashboard — this
epoch is the first UX-iteration pass on top of it, not a partial build.
Tracked under the GitHub milestone "UX Improvements — Dashboard".

- [x] Extract cached data-loading layer into dashboard/data.py, add
      dashboard/__init__.py — behavior-preserving, no UX change yet.
      AppTest-based dashboard tests introduced (tests/test_dashboard.py,
      dashboard_db fixture in tests/conftest.py) to prove the testing
      mechanism before multipage complexity is added.
- [x] Add list_products() (app/services/product_service.py) and
      get_fleet_status() (new app/services/fleet_service.py) — backend only,
      no dashboard changes yet (#68)
- [x] Multi-page navigation via st.navigation()/st.Page() (dashboard/views/),
      product selector sourced from the products table instead of the
      feature-store parquet file (fixes numeric-ID-only display and
      products-with-no-sales-history being invisible) (#69)
- [x] Product Detail page enhancements — forecast horizon slider (1-90,
      matching the API bound), safety_stock/days_of_stock_remaining KPI
      tiles, event-type filter + pagination (#70)
- [x] Fleet Overview page — portfolio-wide KPIs, urgency filtering, deep
      link into Product Detail via a per-row "View" button rather than
      st.dataframe row-click selection, which reproducibly crashed the
      Streamlit server in this environment (#71)
- [x] Admin/Ops page (replay + export controls) — was deferred until #32
      (dashboard auth) landed; now unblocked, so it ships already protected
      instead of exposed. Gated on Epoch 7.3's `role` field
      (dashboard/views/product_detail.py, moved here from dashboard/app.py in #69),
      not just being logged in — confirmation checkbox required before the
      destructive rebuild action is clickable, export mirrors the API's
      always-incremental behavior (#72)
- [x] Optional: .streamlit/config.toml theming polish (#73)

------------------------------------------------------------
EPOCH 7.2 — Real Sales-Data Ingestion
------------------------------------------------------------

Goal: today, data only enters via POST /api/inventory/events one row at a
time, or a demo-only seed script. This epoch adds a generic,
platform-agnostic ingestion path — not tied to a specific POS vendor — that
a future Shopify/Square/etc. adapter could eventually sit behind. Tracked
under the GitHub milestone "Data Ingestion — Sales Integration".

- [x] Shared ingestion core (app/services/ingestion_service.py) — resolves
      each row's product by SKU (new: product_service.get_product_by_sku,
      ProductSkuNotFoundError), calls the existing record_event() per row
      (already idempotent/race-safe), collects per-row results instead of
      failing the whole batch on one bad row
- [x] Generic CSV bulk-import endpoint — POST /api/inventory/events/bulk,
      columns: sku, event_type, quantity, event_id
- [x] Generic HMAC-signed webhook receiver — POST /api/webhooks/ingest,
      reuses the same ingestion core, WEBHOOK_SECRET-based signature
      verification mirroring app/core/auth.py's existing hmac.compare_digest
      pattern

------------------------------------------------------------
EPOCH 7.3 — Role-Based Access Control (RBAC)
------------------------------------------------------------

Goal: SECURITY.md has stated since the JWT-auth arc (#23) that RBAC is a
known, intentional gap — every authenticated user has identical
privileges. This epoch closes it with the minimum viable role model: two
roles (admin/member), gating the two operations that actually need it
today. Directly unblocks #72 (Dashboard: Admin/Ops page — replay + export
controls), which currently frames "protected" as Caddy basic_auth alone
(network-perimeter, all-or-nothing); without this epoch, any signed-in
dashboard user would be able to trigger replay/export once #72 ships its
UI. This epoch does NOT build #72's dashboard page — only the role
column, the auth dependency, API-level gating on POST /api/inventory/replay
and POST /api/inventory/export, and a role field in dashboard session
state for #72 to consume later.

- [x] Add `role` column to `users` (UserRole enum: admin/member,
      server_default="member" for safe backfill of existing rows)
- [x] `require_role()` auth dependency (app/core/auth.py) — composes on
      require_current_user, re-checks the live DB-loaded role on every
      request (no JWT claim, same convention as is_active), raises 403
- [x] Gate POST /api/inventory/replay and POST /api/inventory/export behind
      require_role(UserRole.ADMIN)
- [x] `--role` flag on scripts/create_user.py (default: member); new
      scripts/set_user_role.py for promoting/demoting existing users
      (writes an audit_log "role_changed" entry — the one CLI action in
      this epoch that IS audited, given it's a privilege-escalation
      event, unlike account creation)
- [x] Add `role` to dashboard/auth.py's session-state dict — hook for #72,
      no dashboard UI changes in this epoch
- [x] Update SECURITY.md's auth-model section to describe the role model

------------------------------------------------------------
EPOCH 8 — Kafka Streaming (Optional, deferred — see below)
------------------------------------------------------------

Goal: Process inventory events in real time via Kafka instead of only
synchronous PostgreSQL writes.

**Scoped in detail 2026-07-28** (#76, one Explore-agent codebase audit,
independently spot-verified against source): more expensive than the rough
bullet list below implies, and no concrete need for it has actually appeared
yet — the current synchronous path already gives atomic writes and O(1)
projection reads. Recommendation: **defer indefinitely; if ever pursued,
sequence after Epoch 10** (reasoning below), not as a default next step.

**Real gap the rough bullet list glossed over — dual-write atomicity.**
`record_event()` (`app/services/inventory_service.py:154-168`) already
commits the event insert, the `inventory_state` projection update, and any
recipe/BOM cascade atomically in one transaction (confirmed: single
`db.commit()` at line 168, covering everything `_apply_event()` flushed
first). A producer call "after DB write," as originally phrased below, is a
*second, uncoordinated* write to a second system — the Postgres commit can
succeed while the Kafka publish fails, silently desyncing the topic from the
source of truth, with nothing to detect or repair that gap. Needs an
explicit choice: accept at-least-once-with-retry-and-idempotent-producer
semantics, or add an outbox table (write intent in the same transaction as
line 168, a separate relay polls/publishes it) for a real guarantee.

**Real scope multiplier — zero existing async/worker infrastructure.** No
Celery, no APScheduler, no `BackgroundTasks`, no cron, no queue library
anywhere in this codebase (`requirements.txt` has none). Every current
service in the compose files is either request-driven (`api`, `dashboard`)
or one-shot-and-exit (`migrate`) — there is no precedent for a detached
long-running worker. Kafka would introduce that pattern for the first time,
alongside Kafka itself, not on top of something already proven here.

**Real cost reduction — dedup is mostly already solved.** `event_id`'s DB
unique constraint (`uq_inventory_events_event_id`) plus `record_event()`'s
existing catch-`IntegrityError`-and-return-existing logic
(`inventory_service.py:173-188`) means a projection-updater consumer can
reuse `record_event()`/`_apply_event()` almost unchanged and inherit
exact-once-at-the-DB-layer semantics despite Kafka's own at-least-once
delivery — "deduplication on consumer side" below is largely already built,
not a fresh subsystem.

**Coupling with Epoch 10 is real and asymmetric — the main reason to
sequence after it, not before.** Epoch 10 threads `organization_id` as an
explicit parameter through `record_event()` and requires
`event_id` uniqueness to become `UNIQUE(organization_id, event_id)`. If
Kafka ships first, its message schema necessarily ships without
`organization_id` — and since "replay via compacted topic" below implies
indefinitely-retained messages, that's a permanently org-less poisoned
replay topic once Epoch 10 lands, plus rework on both producer and
consumer. If Epoch 10 ships first, the schema just includes the field from
day one (same as `created_by_id` already does), at ~zero extra cost.

**Other corrections to the original rough shape:**
- "Kafka + Zookeeper" → evaluate KRaft-mode Kafka instead (ZooKeeper-free,
  the recommended production mode since Kafka 3.5+) — cuts an entire second
  stateful sidecar (its own volume, healthcheck, version-compatibility
  matrix), consistent with this repo's existing bias toward minimal stateful
  services (only Postgres + optional MinIO today).
- "Replay via compacted topic" needs to state what it adds beyond the
  already-shipped `rebuild_inventory_state()` (`app/services/replay_service.py`,
  `POST /inventory/replay`) — likely: rebuilding a *consumer's own* derived
  state (e.g. the data-lake writer's Parquet output), not the Postgres
  projection, which already has a working replay path.
- Needs an explicit decision on `app/scripts/export_events.py`/`make export`
  coexisting with vs. being retired by a Kafka data-lake-writer consumer —
  running both risks duplicate or divergent output (different checkpoint
  semantics: Postgres row-id watermark vs. Kafka consumer offsets).
- `scripts/seed_data.py` writes `InventoryEvent` rows directly, bypassing
  `record_event()` entirely — would need to be updated too, or seeded data
  would silently never reach the topic.

Rough shape (unchanged from the original filing, corrections above apply on
top):

- [ ] Kafka (KRaft mode, no Zookeeper) via Docker Compose
- [ ] Outbox-pattern or explicit at-least-once decision for the event
      producer (embed in `record_event()`, the existing single choke point
      for all 3 real call sites — `app/api/inventory.py`,
      `purchase_order_service.py`, `ingestion_service.py`)
- [ ] Projection updater consumer (reuse `record_event()`/`_apply_event()`
      directly — dedup mostly free, see above)
- [ ] Data lake writer consumer (decide coexistence-vs-retirement of
      `export_events.py` first)
- [ ] Replay via compacted topic (scope against what `rebuild_inventory_state()`
      doesn't already cover)

------------------------------------------------------------
EPOCH 9 — ML Platform Maturity
------------------------------------------------------------

Goal: Productionize the ML layer beyond today's single-shot `make train`.

**Scoped in detail 2026-07-28** (#77, one Explore-agent codebase audit,
independently spot-verified against source — confirmed `load_model()`,
`app/services/forecast_service.py:180-211`, has no version/alias concept of
any kind). Splits cleanly into two cheap, real, do-anytime items and two
items that were scoped from a mismatched mental model or don't match this
project's actual current scale (3 seeded products, 30-90 days of data, one
dashboard operator).

- [ ] **Finish model-versioning wiring (cheap, ~50% already done).** The
      MLflow registry already works today — every `train_model()` call logs
      params/metrics and registers a new version
      (`forecast_service.py:38-82`), confirmed by
      `tests/test_forecast.py:134-158`. `docs/model-registry.md` already
      designs a `champion` alias for promotion/rollback, but it's never read
      anywhere in application code — `load_model()` always resolves the
      single fixed filename `prophet_{product_id}.pkl`, with no concept of
      "which registry version is this." Remaining work: wire
      `load_model()`/`train_model()` to the alias mechanism the docs already
      designed. Small, well-bounded — finishing an existing design, not
      building a new one.
- [ ] **Automated retraining via host cron (cheap, 0% done today).** No
      scheduler exists anywhere in this codebase (no cron, no GitHub Actions
      `schedule:`, no worker service, no API trigger). At this project's
      actual scale, the proportionate answer is a plain host cron entry
      calling the existing `make features && make train` — works today
      against the standing local `docker-compose.prod.yml` deployment from
      #74, doesn't need a hosted VPS. Do this *after* fixing
      `build_features()`'s full-table-rebuild-every-run behavior
      (`app/services/feature_service.py:14-53` — already scoped as an Epoch
      10 "for operability" fix) if that lands first; harmless either way at
      current data volume.
- [ ] **Re-scoped: Prophet decomposition surfacing, not "feature importance"
      (small, optional).** Prophet is univariate here — training only ever
      uses `ds`/`y` (`forecast_service.py:109`); 2 of the 5 columns
      `build_features()` computes (`rolling_avg_7d`, `units_purchased`) are
      unused, and there are zero `add_regressor()` calls anywhere.
      "Feature importance" as originally filed (SHAP/tree-model framing)
      doesn't apply to a univariate additive decomposition model. The real,
      proportionate substitute: surface Prophet's own trend/seasonality
      decomposition (already computed by `predict()`, never shown in the
      dashboard) and/or actually wire the 2 unused columns in as regressors.
- [ ] **Deferred indefinitely: A/B testing framework for models.**
      Disproportionate at current scale — no real traffic exists to split
      (one restaurant, one dashboard viewer, 3 SKUs), and it would reverse
      `docs/model-registry.md`'s explicit design decision to keep the
      registry out of the request path. No comparison/scoring
      infrastructure exists to build on today (only in-sample MAE at
      training time). Revisit only once there's real multi-org or
      multi-source traffic to split — realistically not before both Epoch
      10 and Epoch 11 exist.

**Sequencing vs. Epoch 10:** the two cheap items above are safe to build any
time, independent of whether/when Epoch 10 starts. Epoch 10 already plans
per-org partitioning of `MODELS_DIR`/MLflow names "for operability," and
`app/core/storage.py`'s path-agnostic design (recursive `glob()`,
content-hash `cache_key()`) means that's a path-rename, not an architecture
change, if these ship first — mildly wasteful to touch `build_features()`'s
scheduling twice, not a real redo.

------------------------------------------------------------
PATH A — Restaurant Deployment (shipped 2026-07-26, PRs #100-106)
------------------------------------------------------------

Goal (added 2026-07-26, see full discussion in the roadmap session this
epoch split came from): get one real restaurant — a friend's — running
this daily, in weeks not months. None of the general-audience machinery
below (multi-tenancy, integrations, org isolation) is needed for this —
it's one business, one deployment. This is deliberately sequenced ahead of
Epoch 10+ (Path B) — see "Why Path A comes first" below.

- [x] Recipes / BOM for restaurants — dishes consume ingredients in fixed
      quantities on SALE, a simpler version of Epoch 14's manufacturing/BOM
      idea. The actual feature requested. (`app/services/recipe_service.py`)
- [x] `WASTE` event type — spoilage/waste tracked distinctly from `DAMAGE`
      (`app/models/enums.py`)
- [x] Real `PurchaseOrder` object — supplier, line items, quantities; turns
      a forecast + current stock into an actual, persisted, actionable
      order instead of just a restock number on the dashboard
      (`app/models/purchase_order.py`)
- [x] Day-of-week-aware forecasting — restaurant demand shape is spikier
      (weekday/weekend) than typical e-commerce SKU demand; tune Prophet's
      seasonality rather than assume the existing model generalizes as-is
      (PR #103, `weekly_seasonality=True`, backtested in
      `tests/test_forecast.py`) — this checkbox was found stale (still
      unchecked despite shipping) during #76/#77's 2026-07-28 scoping pass
- [x] CLI wrapper around the Makefile (`ims start`/`ims setup`/`ims backup`)
      — doubles as the first-run setup wizard, no separate wizard needed
      (PR #106, `scripts/ims.py`)
- [x] Backup routine — cron/rsync of Postgres + the local data lake to a
      second location; explicitly not S3/MinIO, unnecessary at this scale
      (`scripts/backup.sh`, `scripts/restore.sh`)
- [ ] Explicitly skip for Path A: S3/object storage, multi-tenancy,
      integrations, AWS deployment — none of it serves one restaurant

Rough estimate: 2-4 weeks of focused evenings/weekends. Exit criteria: the
friend runs this daily for real service and it saves him real time, or
tells us clearly what's wrong with it.

------------------------------------------------------------
Why Path A comes first (not a decision to force on Path B)
------------------------------------------------------------

"General audience eventually" and "restaurant first" aren't competing
choices — the architecture underneath (event sourcing, forecasting,
ingestion core, purchase orders as a concept) is already general-purpose;
none of it is restaurant-specific. Recipes/BOM for restaurants is just the
first domain-specific layer on top of it, in the same shape a retail BOM
or a services-business module would be later.

The honest reason not to design "for a general audience" directly right
now: nobody can answer what a general audience needs in the abstract — it
takes a real user with real daily friction to find out what actually
matters versus what only sounds important. Path A *is* the responsible way
to get to Path B — not a detour from it.

Epoch 10+ below (Path B) was originally scoped to start once Path A had
real signal that more than one business wants this. **That signal never
arrived — contact with the friend running Path A was lost, so there is no
real-world usage data and no way to get any in the near term.** As of
2026-07-27, whether to start Epoch 10 at all is an explicit open decision;
the scoping below exists so that decision can be made with real numbers
instead of the original guess.

**Decided 2026-07-27: #74 (deploy the self-hosted stack to a real VPS)
happens first, before Epoch 10 starts.** Not a hard technical dependency —
Epoch 10 doesn't require a live deployment to exist — but the cheapest way
to get *some* real signal before committing ~2-2.5 months to a hard-to-reverse
architectural change is to actually run the current single-tenant product
somewhere real first. #74 was previously deferred on a no-cost budget
constraint; revisit that constraint before committing to a specific host.
One concrete option if the constraint stands: Oracle Cloud's Always Free
tier (genuinely permanent, not a 12-month trial — up to 4 ARM Ampere A1
cores / 24GB RAM), which the current stack should run on cleanly — Prophet
1.3.0 ships a real Linux `aarch64` wheel, `cmdstanpy` is a pure-Python
universal wheel, and the only piece needing compilation (CmdStan itself,
via `install_cmdstan()`) is a standard portable C++/`make` build with no
known ARM issue. `make train` also isn't containerized today (runs as a
host command per the Makefile/README quickstart) — the deployed API/
dashboard containers only ever `load_model()` a pre-trained `.pkl`, so
even a training-side ARM problem, if one ever turned up, wouldn't block
serving. `docker/Dockerfile`'s own base-image comments already show it was
pinned with `arm64` in mind (manifest-list digest, not a single-arch tag).

**2026-07-28: no-cost budget constraint still stands** — every VPS option
checked (including Oracle's Always Free tier above) requires a card on file
for identity verification, even when nothing gets charged, which isn't
available. Rather than block on that, ran the actual production-mode stack
(`docker-compose.prod.yml`, no Caddy/no domain yet) end-to-end on real
hardware, in an isolated Docker project/volume so it couldn't touch the
existing dev stack's data. Every documented step in
`docs/deployment/self-hosted.md` held up exactly as written outside local
dev shortcuts: 15 Alembic migrations applied clean to a fresh DB; Gunicorn
came up with real multi-worker concurrency; Postgres confirmed genuinely
unpublished to the host (`ports: !override []`); real account creation,
login, and JWT-gated `/api` routes all worked; `restart: unless-stopped`
correctly did *not* restart after an explicit `docker kill`/`stop` (by
design) but correctly did auto-restart after an unmediated crash
(RestartCount incremented); a full `down`/`up` cycle preserved the Postgres
volume; and `scripts/backup.sh` + `scripts/restore.sh` were proven to
actually round-trip real state (created a 2nd user, took a backup, created
a 3rd user, restored the earlier backup, confirmed the 3rd user's login now
401s while the first two still work — not just "the script exited 0").
Zero bugs found. **What's still open, and now the actual remaining scope of
#74**: nothing here tested real public reachability, a real domain, or the
Caddy HTTPS overlay — that still needs an actual reachable host, which
remains blocked on the card-free-hosting question above.

**Closed 2026-07-28.** Also fixed a real pre-existing bug found along the
way (dashboard healthcheck was checking the API's port, not its own —
PR #118), and demonstrated genuine public reachability via a Cloudflare
quick tunnel — a real `https://*.trycloudflare.com` URL served the live
dashboard, fetched externally and confirmed working (PR #119, which also
documents why a *permanent* address isn't achievable this way: both routes
to a persistent named Cloudflare Tunnel require either a card or a domain
already owned elsewhere). Closing #74 on that basis — the self-hosted path
is fully verified and public reachability is proven possible, just not
permanent. Reopen if a card or an owned domain becomes available.

------------------------------------------------------------
EPOCH 10 — Multi-Tenancy (Path B, shipped 2026-07-28 to 2026-07-30, PRs #153-#170)
------------------------------------------------------------

**Decision to start (2026-07-28):** deliberately started without waiting for
real multi-tenant demand signal — explicitly for portfolio/learning value,
not because a second business is lined up. Sequenced as 16 PRs (GitHub
milestone "Epoch 10 — Multi-Tenancy", issues #137-#152), built one PR at a
time. See PRs #153-#170 for the full history.

Goal: one deployment can safely serve more than one business. Has to
happen before integrations or a hosted offering — retrofitting tenant
isolation onto an existing schema/event log is much harder than building
it in from the start, and it's a better foundation now that real user
accounts (`users`, JWT, roles) already exist than retrofitting onto the
old shared-API-key model.

**Scoped in detail 2026-07-27** (three parallel codebase audits + one
design pass, independently re-verified against source, not just the
audits' word) — full reasoning in the session, condensed here:

**Architecture: shared schema + `organization_id` on every table, enforced
via composite foreign keys — not schema-per-tenant, not database-per-tenant.**
Matches the codebase's existing convention of threading owner/actor ids as
plain columns + explicit function parameters (`record_event(...,
created_by_id)`); needs no new infrastructure class. Self-hosted stays a
*mode*, not a fork: schema always has `organization_id`, but every
self-hosted deployment bootstraps exactly one org row and a feature flag
(`ALLOW_MULTIPLE_ORGS`, default `false`) hides multi-org UI from it
entirely — no retrofit tax paid twice.

**Load-bearing decision: keep surrogate integer PKs (`product.id`, etc.)
globally unique across orgs; only business/natural keys (`sku`, `event_id`)
become org-scoped** (`UNIQUE (organization_id, sku)` /
`UNIQUE (organization_id, event_id)` — confirmed only these two need to
change, `users.email` deliberately stays globally unique, one person one
login, no org-selection step). This eliminates false collision risk in the
feature store and Prophet/MLflow model naming that an earlier, less
verified pass through this scoping assumed (confirmed: `Product.id` is a
plain global `Integer` PK with no per-org reset), while still meaning
**every** table —
`products`, `suppliers`, `inventory_events`, `inventory_state`,
`recipe_items`, `purchase_orders`, `purchase_order_lines`, `audit_log`,
`users` (9 tables) — needs the column, backfilled via its parent where one
exists (not a hardcoded constant), plus `UNIQUE (organization_id, id)` on
parents and composite FKs on children so cross-org references are
structurally impossible at the DB level — the same "DB-enforced invariant,
not just code convention" discipline already established by the
`audit_log` tamper-protection trigger and `_safe_path()`'s traversal
guard.

**`organization_id` propagation is explicit parameter-threading, not a
JWT claim and not a contextvar.** Same reasoning as why `role` isn't
trusted from the JWT today (`require_current_user` always re-fetches the
live `User` row so revocation/role changes take effect without a token
refresh) — a `get_current_org_id()` dependency composes on
`require_current_user` exactly the way `require_role()` already does, and
every service function gains an explicit `organization_id` parameter, the
same shape `created_by_id`/`actor_id` already take everywhere.

**Full pipeline, not just Postgres/API** — the entire downstream chain has
zero tenant dimension today and each stage needs its own fix, not one
generic one: Parquet export gains an `org_id=` partition level + column
(current date-only partitioning and single global checkpoint watermark
stay correct as-is, since surrogate PKs remain globally unique); dbt's 3
warehouse models gain an `organization_id` column plus a join-boundary
test; the feature store and Prophet model files/MLflow registry get
per-org partitioning/naming for operability and to fix `build_features()`
rebuilding the *entire* table every run (not for collision safety — there
isn't any); every dashboard loader in `dashboard/data.py` needs the org id
threaded through, including as part of the `@st.cache_data` cache key
itself (`st.cache_data` caches by argument value — omitting it would leak
cached results across orgs viewed in the same process).

**Two real gaps this epoch must close as the same work, not separately:**
1. `recipe_service.py`/`purchase_order_service.py`'s mutation functions
   (`update_recipe_item_quantity`, `remove_purchase_order_line`,
   `submit_purchase_order`, etc.) look up records by bare integer ID with
   **zero ownership check** today — harmless only because there's
   currently one implicit tenant. IDOR-shaped; needs a dedicated
   regression test per function once org-scoping lands.
2. Webhook ingestion (`POST /api/webhooks/ingest`) authenticates via one
   *global* `WEBHOOK_SECRET` with no org identity anywhere in the payload
   or route — confirmed in `app/core/auth.py`'s `require_webhook_signature`.
   Breaks outright once `record_event()` requires an org id. Fix: per-org
   webhook secret, org identified in the route
   (`POST /webhooks/{organization_id}/ingest`) — this is also a
   prerequisite Epoch 11's real connectors need anyway (per-org, per-source
   credentials), so it's not wasted work building it here.

- [x] `organizations` table + bootstrap row; `organization_id` added to all
      9 tables above, backfilled via parent where one exists
- [x] `products.sku` / `inventory_events.event_id` become
      `UNIQUE (organization_id, ...)` — the `event_id` change landed in
      the same PR as the 3 call sites in `inventory_service.py` that query
      it (idempotency pre-check, duplicate-catch retry, recipe-cascade
      derived id), not a follow-up (PR 6/16, #142)
- [x] Composite FKs (`UNIQUE (organization_id, id)` on parents,
      `FOREIGN KEY (organization_id, product_id) REFERENCES
      products(organization_id, id)` on children) so cross-org references
      are impossible at the DB level, not just checked in code
- [x] `get_current_org_id()` dependency (composes on `require_current_user`
      like `require_role()` does) wired into all route files; every
      service function that touches org-scoped data gets an explicit
      `organization_id` parameter
- [x] Recipe/PO ownership-check gap closed (PR 9-10, #145-#146) + per-org
      webhook secret + `/webhooks/{organization_id}/ingest` routing
      (PR 12, #148)
- [x] Parquet export `org_id=` partition + column (PR 13, #149); dbt models
      + `organization_id` + join-boundary test (PR 14, #150); feature
      store and Prophet model files/MLflow registry partitioned per org
      (PR 15, #151) — also resolves how #22's S3-capable storage, shipped,
      is org-partitioned, since the same `org_id=` partition level applies
      whether the data lake root is local disk or S3
- [x] Dashboard: `organization_id` in `dashboard/auth.py`'s session dict
      (same precedent as adding `role` ahead of #72's admin gate); every
      `dashboard/data.py` loader and its `@st.cache_data` key updated
- [x] Cross-org isolation test suite (same-SKU/same-event_id-different-org,
      cross-org 404s on PO/recipe mutation, fleet/forecast/restock
      scoping, webhook→org resolution) consolidated in
      `tests/test_multi_tenancy.py`, plus [docs/multi-tenancy.md](docs/multi-tenancy.md)
      matching `docs/model-registry.md`'s style (PR 16, #152)
- [ ] Explicitly deferred to a later hardening pass, not required for exit
      criteria: Postgres RLS as a second, DB-enforced layer on top of the
      composite-FK design (same "code convention + DB backstop" pattern as
      the audit_log trigger)

**Closed 2026-07-30.** Original estimate (below, from the 2026-07-27
scoping pass) was ~7.5-10.5 weeks; actual delivery was ~2.5 days across
16 PRs, working through them sequentially with real end-to-end
verification (real scratch Postgres, real dbt runs, real Prophet
training against two orgs, not just mocked unit tests) at each step —
see individual PR descriptions (#153-#170) for what was verified at each
stage. A real live bug was found and fixed along the way (`replay`
wiping every org's inventory projection, not just the caller's), along
with several real IDOR gaps (bare id-only lookups with zero ownership
check) — both categories confirmed via direct regression tests, not
just inferred from a code read. See [docs/multi-tenancy.md](docs/multi-tenancy.md)
for the architecture summary and what's still deliberately deferred.

Original rough phased estimate (re-derived 2026-07-27 from the actual
codebase, not a generic guess): design lock-in 0.5-1wk, core schema +
write path 1.5-2.5wk (highest-risk — the idempotency-critical
`with_for_update()` row lock), services/API/auth 1.5-2wk, pipeline
1.5-2wk, dashboard 1wk, cross-org tests + hardening 1.5-2wk. **Total
~7.5-10.5 weeks (~2-2.5 months) for multi-tenancy alone** — see the note
at the end of this Path B section for what this means for the combined
Epochs 10-15 estimate.

Exit criteria (met): two unrelated businesses could run on the same
instance without either seeing the other's data, even under a bug.

------------------------------------------------------------
IMS DESKTOP — Native Installers (Linux shipped, Windows/Mobile in progress)
------------------------------------------------------------

Not a Path A/B epoch — a separate track (`#174`, filed 2026-07-31) for
distributing IMS as an installable native app instead of a
docker-compose-and-a-terminal deployment, aimed at non-technical
end users. Built on [Tauri](https://tauri.app/), wrapping the same
Docker Compose stack (desktop) or connecting to a remote one over
Tailscale (mobile) — see [docs/multi-tenancy.md](docs/multi-tenancy.md)-style
architecture notes in [docs/deployment/desktop-app.md](docs/deployment/desktop-app.md).

**Linux desktop — shipped.** `#189-195` (account bootstrap via a
bootstrap-gated `POST /api/auth/register`, Docker lifecycle management
from Rust with live launch-phase events, first-run wizard, GPG-signed
`.rpm` packaging). **First public release: `v0.1.0`**
(https://github.com/sinan-can-demir/ims/releases/tag/v0.1.0) — real
signed `.rpm`, verified end-to-end (built, launched, signature
independently re-verified against the published download, not just the
local file).

**AppImage packaging — fixed, unofficial.** `#212` tracked a real
linuxdeploy bundling bug (RUNPATH patching corrupting bundled libraries,
eventually root-caused to a stale-`DT_INIT`-then-NX-violation chain —
see the issue's own comment history for the full investigation). Fixed
by skipping RUNPATH patching entirely and restoring stock system
libraries post-build (`tauri/scripts/restore_stock_appimage_libs.py`,
`make desktop-build-appimage`). Deliberately **not** an official
release target — excluded from CI and not chained into `desktop-build`,
since the fix embeds the *build host's own* system libraries as
replacements. `.rpm` remains the only officially distributed Linux
format.

**Windows — partially shipped, not yet fully verified.** `#225`
(extracted Tauri out of `desktop/` into its own `tauri/` directory,
prerequisite for both Windows and mobile) and `#226` (Windows bundle
target, `.msi`/`.exe`) shipped. **Real gap:** the actual
Windows-hardware verification pass for `#226` never happened — it was
merged via a batch "merge all green" before a promised real-machine test
ran, so several Windows-specific concerns (named-pipe Docker
communication, MSI vs. NSIS installer choice, `resource_dir()` path
resolution, TIME_WAIT socket behavior) are reasoned-about, not verified.
`#228` (CI job to build the Windows artifact), `#229` (Authenticode
code-signing, parity with the `.rpm`'s GPG signing), `#230` (Windows-specific
first-run/error-state UX), and `#231` (end-user setup docs for Windows)
are open, not started. `#268` (Docker Desktop's admin/UAC friction for
non-technical Windows users) is blocked on real Windows hardware — a VM/Wine-based
verification route was explored and correctly ruled out as untrustworthy
signal.

**Mobile — architecture decided, core pieces shipping incrementally.**
`#227` resolved the fundamental constraint (Docker can't run on
iOS/Android) as: native Tauri Mobile wrapping the *existing* dashboard
UI (not a from-scratch native rewrite, not a PWA), reached over a
Tailscale VPN connection rather than a public tunnel. `#232` (configurable
backend server address, since mobile has no local Docker to default to)
and `#234` (full Android SDK/NDK toolchain + a real working APK, verified
via `unzip -l`/`aapt2`, not just a build-success message) shipped.
`#269` (Android's cleartext-HTTP block, correctly scoped to `*.ts.net`
domain matching rather than the original CGNAT-range framing, since
Android's Network Security Config has no CIDR primitive) shipped. `#233`
(login/session handling) resolved a wrong premise in the issue itself —
the dashboard's login is a server-side Streamlit session, not a client-held
token, so there's no native Keychain/Keystore work needed — and shipped the
actual missing piece (webview navigation into the dashboard once a host is
configured). Remaining open: `#235` (Android/iOS CI), `#236` (touch/UI
responsiveness audit), `#237` (app store packaging), `#238` (end-user
docs), `#245`/`#246` (first-run polish: loading states, a way back to
the settings screen, connection/auth error handling) — iOS specifically
is deferred indefinitely (no Mac available to build/test on).

------------------------------------------------------------
FOOD COST VISIBILITY — Waste Entry, Toast Connector, Cost Alerts (Path A continuation)
------------------------------------------------------------

Goal: close a real, structurally-confirmed gap — as a packaged desktop
app, IMS gives a non-technical user no obvious way to get day-to-day data
in at all (confirmed via a direct codebase check: the only mutating form
anywhere in `dashboard/views/*.py` is Purchase Orders; there's no manual
"log a sale/waste/adjustment" screen).

**Scoped 2026-09-04** via a structured two-persona discovery simulation
(no real user exists yet to interview for real) — see
[docs/product/food-cost-visibility-discovery.md](docs/product/food-cost-visibility-discovery.md)
for the full findings, methodology, and direct quotes. Distinct from
Epoch 11 below: this is Path A (restaurant-specific, Toast POS) driven by
concrete discovery findings, not Path B's general small/mid-business
e-commerce connectors (Shopify/QuickBooks/WooCommerce) — different
integration category, don't conflate the two.

**The reframe that drives sequencing:** the discovery's own persona
didn't want more data-entry screens — she wanted **food cost percentage
(COGS ÷ revenue)** visible and updating regularly, currently only
available quarterly from an accountant. Every item below is plumbing
toward that number; the last item is the actual deliverable, not a
downstream nice-to-have gated on the others being perfect.

**Phase 1 — Waste quick-entry (must-have, cheapest, highest-leverage):**
- [ ] New `dashboard/views/waste_entry.py` page (`st.Page`, registered in
      `dashboard/app.py`'s `st.navigation()`) + `dashboard/waste_actions.py`
      (mutating service calls via `SessionLocal()`, same pattern as the
      existing `po_actions.py`/`recipe_actions.py`) — product picker +
      event-type picker (defaulting to WASTE) + a quantity number input,
      calling the existing `record_event()` service function directly.
      Tap/pick-list/number only — no free-text field, per the discovery's
      explicit finding that anything requiring a composed sentence doesn't
      survive a rush shift.
- [ ] No new auth work needed for the "stays logged in" requirement — the
      dashboard's session is already server-side (Streamlit, not a
      client-held token) and already has no time-based expiry on a
      disconnected-but-not-closed session (confirmed against the
      installed Streamlit source this session, see PR #305's discussion
      on #233). Verify this holds for the actual mobile webview
      (background the app for an extended period, confirm no re-login) as
      a real device test — not yet done live, per PR #305's own disclosed
      gap.
- [ ] Cache invalidation: reuse `invalidate_product_views`/
      `invalidate_fleet_status` (already built for exactly this shape,
      see issue #283/PR #295).

**Phase 2 — Purchase Order price-creep flag (must-have, cheap).**
**Shipped 2026-09-04.**
- [x] At `add_purchase_order_line()` (`app/services/purchase_order_service.py`),
      compare the new line's `unit_cost` against the most recent prior
      line for the same `product_id`; surface a simple flag if higher.
      `unit_cost` is already a tracked field — no schema change needed.
      Scoped to `product_id` only, not also `supplier_id` — Maria's own
      framing ("this item cost more than last time") was product-general,
      not supplier-specific, and a price jump from switching suppliers is
      still worth flagging, not excluded as noise.
- [x] **Real pre-existing bug found and fixed along the way** (see
      `docs/wiki/po-dashboard-never-collects-unit-cost.md`): neither
      dashboard PO form (`create_po_form` or `add_line_form`) had a
      `unit_cost` input at all — every dashboard-created PO line had
      `unit_cost = None`, making this phase's flag meaningless without
      also fixing that.

**Phase 3 — Toast POS connector (must-have, largest lift):**
- [ ] Credential-based "Connect to Toast" flow — a real login-style
      OAuth/credential handshake, explicitly **not** a raw API-key paste
      (the discovery was specific that the latter is a non-starter for a
      non-technical owner).
- [ ] One-time UI to map Toast menu items to IMS products — reuses the
      existing `Product` table as-is (a "finished dish" is already just a
      `Product` row with `recipe_items`, same concept Recipes/BOM already
      uses); no new schema concept required.
- [ ] Periodic sync job translating Toast's sales report into the
      existing generic ingestion shape (`{sku, event_type: "SALE",
      quantity, event_id}`) and calling the already-built, already-shared
      `app/services/ingestion_service.py::ingest_events()` — the same
      core the CSV importer and webhook receiver already use. Batch
      (daily or weekly), not real-time — the discovery was explicit that
      real-time isn't needed and a nightly cadence already stretches what
      a busy owner would tolerate.
- [ ] No in-app scheduler exists in this codebase (confirmed, see Epoch 9
      above) — follow the same proportionate pattern already established
      for automated retraining: a plain host cron entry calling a new
      sync script (`scripts/sync_toast_sales.sh`, mirroring
      `scripts/retrain_cron.sh`'s shape), not new scheduling
      infrastructure.

**Phase 4 — Food-cost % dashboard tile (the actual deliverable):**
- [ ] Real blocker found while scoping, not from the interview: **IMS has
      no revenue data today.** `Product` has no `selling_price`, and
      IMS-native `SALE` events carry only quantity, never a dollar
      amount. This phase cannot ship for any org before Phase 3 (Toast
      carries per-item sale price) — unless a manual `selling_price`
      fallback field is scoped in for POS-less orgs, a decision not yet
      made.
- [ ] Once a revenue source exists: a dashboard tile computing
      COGS-vs-revenue from whatever data streams are live so far (even a
      partial, improving number matters more here than a complete one —
      per the discovery's own framing) — and this tile, not a form,
      should be the thing a first-time user sees, addressing the
      "blank dashboard, no obvious action" first-run confusion the
      discovery surfaced.

**Deliberately not in this scope (see discovery doc for reasoning):**
real-time POS sync, dedicated kitchen hardware/kiosk, any free-text entry
field, returns/credit tracking.

------------------------------------------------------------
EPOCH 11 — Real Integrations (Path B, highest leverage once started)
------------------------------------------------------------

Goal: move from "generic webhook ingestion" (Epoch 7.2, shipped) to
"plugs into what a small seller already uses" — Shopify, then
QuickBooks Online or Xero, then WooCommerce, then a shipping/fulfillment
connector. Each normalizes into the existing `InventoryEvent` shape via
the shared ingestion core, so analytics/forecasting/dashboard need zero
changes to support a new source.

**Sequencing (2026-07-27):** right after Epoch 10 — the first connector
(Shopify) is the first real-world validation of the multi-tenancy
plumbing, and Epoch 10 already forces building per-org webhook identity
that this epoch needs anyway.

Exit criteria: a Shopify seller can connect their store and see inventory
update automatically, with zero manual CSV work.

------------------------------------------------------------
EPOCH 12 — Order Management Layer (Path B)
------------------------------------------------------------

Goal: `Order`/`OrderLine` entities referencing one or more
`InventoryEvent`s, with a status/state machine (placed → fulfilled →
shipped → returned) separate from the immutable event log. Ties Epoch 11's
connectors' incoming sales into orders, not just raw SALE events.

**Sequencing (2026-07-27):** after Epoch 11's first connector ships (real
order data to validate against), reusing Epoch 10's composite-FK
org-scoping pattern for `Order`/`OrderLine` from day one rather than
inventing a new one.

Exit criteria: look up "order #1234" and see its full lifecycle, not just
infer it from a pile of events.

------------------------------------------------------------
EPOCH 13 — Light Front-Office Features (Path B, pick one)
------------------------------------------------------------

B2B ordering portal (recommended — smaller surface area, showcases the
event-sourced core) or a basic POS (bigger lift, only if targeting
brick-and-mortar sellers). Pick based on target user, not both at once.

**Sequencing (2026-07-27):** after Epoch 12 if the recommended B2B-portal
option is chosen (needs order management underneath to be meaningful);
re-estimate separately if the POS alternative is picked instead — assume
materially larger, not covered by this estimate.

------------------------------------------------------------
EPOCH 14 — Manufacturing / BOM (Path B, optional, segment-dependent)
------------------------------------------------------------

Skip unless there's a specific maker segment that needs it — a full
`BillOfMaterials` + `PRODUCTION` event type + cost roll-up, the general
version of Path A's restaurant-specific recipes/BOM above.

**Sequencing (2026-07-27):** independent of Epochs 11-13, can run any time
after Epoch 10. Don't refine this estimate further without real
maker-segment signal, per the original framing above.

------------------------------------------------------------
EPOCH 15 — Onboarding & Trust Infrastructure (Path B)
------------------------------------------------------------

Not code-heavy, but necessary before anyone non-technical can use this: a
setup wizard or one-command hosted signup, a real docs site, a
managed/hosted tier option, status page + backup/restore runbook + basic
SLA language if offering hosting.

**Sequencing (2026-07-27):** split in two, not "last" as a whole. The
org-bootstrap/setup-wizard half is easiest to build *alongside* Epoch 10,
while the org-creation code path is fresh — don't bolt it on afterward.
The other half (status page, SLA language, managed-tier billing) only
makes sense once there's an actual hosted tier to sell, so that half stays
last, after Epochs 11-14.

------------------------------------------------------------
What NOT to prioritize (Path B)
------------------------------------------------------------

- EDI / big-box retail compliance — high effort, only matters once there's
  a customer segment selling into big retailers. Don't build speculatively.
- Full accounting suite — integrate with QuickBooks/Xero (Epoch 11), don't
  try to replace them.
- A marketplace of 700 integrations — impossible for a solo dev to match
  Cin7 here. Winning 3-4 integrations well beats a long tail of shallow ones.

**Original estimate for Path B (Epochs 10-15) is stale, superseded
2026-07-27:** the original rough total ("2-4 months of solo part-time
work," with multi-tenancy priced at "2-4 weeks") came from an earlier
planning session (`~/Downloads/ims-manual-roadmap.md`) before Epoch 10 was
scoped against the actual codebase. That scoping pass put Epoch 10 alone
at **~7.5-10.5 weeks (~2-2.5 months)** — see Epoch 10 above for the full
breakdown and reasoning — which by itself could consume nearly the entire
old combined budget. Epochs 11-14's original per-item estimates (each
integration 1-2 weeks, order management 1-2 weeks, front-office 2-3 weeks)
haven't been re-scoped in the same detail and should be treated as
unverified rough guesses, not re-derived numbers, until each is actually
scoped the way Epoch 10 now has been — likely once Epoch 10 is underway
and the org-scoping pattern it establishes is concrete enough to estimate
against. Don't quote a combined Path B total until that happens.

------------------------------------------------------------
Full Pipeline (Current)
------------------------------------------------------------

make up          → start Docker stack  
make migrate     → apply Alembic migrations  
make test        → run pytest suite  
make test-e2e    → run bash E2E tests  
make export      → export events to data lake  
make dbt-run     → build warehouse models  
make features    → build feature store  
make train       → train Prophet models  
make dashboard   → start Streamlit dashboard at localhost:8501  

------------------------------------------------------------
Long-Term Vision
------------------------------------------------------------

Simple CRUD API
        ↓
Event-Driven System       ✅ Complete
        ↓
Batch Data Platform       ✅ Complete
        ↓
Data Warehouse (dbt)      ✅ Complete
        ↓
ML Platform               ✅ Complete
        ↓
Application Layer         ✅ Complete
        ↓
Production Hardening      ✅ Complete (self-hosted + AWS-Terraform-written; see Epoch 7 above)
        ↓
Multi-Tenancy (Path B)    ✅ Complete — see Epoch 10 above
        ↓
Native Desktop/Mobile     ✅ Linux shipped (v0.1.0) — Windows/Mobile in progress, see "IMS Desktop" above
        ↓
Kafka Streaming           ← Deferred indefinitely (#76) — no real-time-processing demand signal
        ↓
ML-Driven Intelligence    ← Future — see Epoch 9 above (scoped into 2 cheap do-anytime items,
                             1 re-scoped optional item, and 1 deferred-indefinitely item; none
                             started yet)