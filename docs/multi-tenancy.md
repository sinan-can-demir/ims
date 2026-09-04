# Multi-Tenancy (Epoch 10)

IMS is a shared-schema multi-tenant application: one deployment, one
database, every org-scoped table carries an `organization_id` column.
Not schema-per-tenant, not database-per-tenant — see ROADMAP.md's Epoch
10 section for the full reasoning behind that choice. This doc is the
architecture summary: what's enforced where, and what's explicitly not
done yet.

## Self-hosted stays single-org by default

Every self-hosted deployment bootstraps exactly one org row (id=1,
"Default Organization", via migration `6eb479a8a33c`) and
`ALLOW_MULTIPLE_ORGS` defaults to `false` (`app/config.py`). There's no
self-service org creation — `scripts/create_organization.py` is
CLI-only, same shape as `scripts/create_user.py`. A single-tenant
deployment never sees or pays for any of this: every user lands in org
1, every query's `organization_id` filter is a no-op there.

## What's enforced where

**DB layer — structural, can't be bypassed by a code bug:**

- Every org-scoped table has an `organization_id` column, `NOT NULL`,
  `server_default='1'` (safe backfill for pre-Epoch-10 rows).
- Parent tables (`products`, `suppliers`, `purchase_orders`, `users`)
  have `UNIQUE (organization_id, id)`, letting children declare composite
  foreign keys: `FOREIGN KEY (organization_id, product_id) REFERENCES
  products (organization_id, id)`. A child row's org and its parent's org
  must agree, or the `INSERT`/`UPDATE` fails at the database — not just a
  convention an application bug could silently violate. See migrations
  `49570bffe51e`, `688eb809961b`, `48acda15ea39`.
- `products.sku` and `inventory_events.event_id` are `UNIQUE
  (organization_id, sku/event_id)`, not globally unique — two orgs can
  use the same SKU or client-supplied idempotency key without colliding
  (migration `ffdda217be31`).
- **Load-bearing decision:** surrogate integer PKs (`products.id`, etc.)
  stay globally unique across every org — not reset per org. This is
  what makes cross-service joins on a bare `product_id` (e.g.
  `warehouse_service.build_fact_table()`) safe without every single join
  needing an org check to avoid a wrong match; see "Analytics pipeline"
  below for where an explicit org check is still added anyway, and why.
  `users.email` is also deliberately globally unique — one person, one
  login, no org-selection step at auth time.

**Application layer — explicit parameter threading, not implicit context:**

`organization_id` is never read from a JWT claim or a contextvar. Every
route resolves it via `get_current_org_id()` (`app/core/auth.py`), which
composes on `require_current_user()` the same way `require_role()` does
— it re-reads the live `User` row on every request, so moving a user to
a different org takes effect on their very next request, no token
refresh needed. Every service function that touches org-scoped data
takes an explicit `organization_id` parameter (default `1`, for the
staged rollout this arc was built as — see "How this was built" below)
and filters its own queries by it. There is no ambient/global org
context anywhere in the service layer.

## Webhook ingestion

`POST /api/webhooks/{organization_id}/ingest` resolves org from the
route path, not from any implicit context — the org is public (it's in
the URL), but the request only authenticates if `X-Webhook-Signature`
matches *that org's own* `organizations.webhook_secret` (`NOT NULL` —
every org gets a real random secret at creation time, and the endpoint
fails closed if it's ever unset, rather than treating that as
"verification disabled"). A leaked or brute-forced secret for one org
authenticates requests to that org's ingestion endpoint only. See
`SECURITY.md`.

## Analytics pipeline

The data lake, warehouse, feature store, and model registry all follow
the same pattern: **one shared root, `org_id={organization_id}` as a
real path/partition level within it** — not one root per org, and not
n+1 copies of the pipeline. `organization_id` is also kept as a real
*column* in the Parquet/warehouse output, not just implied by the
directory it's found in.

- `data_lake/inventory_events/org_id={org}/year=/month=/day=/*.parquet`
  — export itself (`export_service.export_inventory_events()`) is
  deliberately **not** org-filtered; it's one whole-deployment run per
  checkpoint (the checkpoint is a single global `InventoryEvent.id`
  high-water mark, since that's one sequence shared by every org), which
  then partitions its own output by org on write.
- dbt's `fact_inventory_events` model joins `stg_inventory_events` to
  `dim_products` `ON e.product_id = p.product_id AND e.organization_id =
  p.organization_id`. The second clause is a **join-boundary invariant
  check, not a correctness fix by itself** — `product_id` being globally
  unique already means this join could never actually match the wrong
  product. It's the same "verify the invariant explicitly instead of
  just trusting it" discipline the composite FKs apply at the DB layer,
  applied here at the analytics layer where there's no FK to enforce it
  structurally. `tests/join_boundary_fact_inventory_events.sql` (a
  custom dbt singular test) regression-tests this directly — proven to
  actually catch a mismatch, not just always pass, by manually
  corrupting a materialized row and confirming the test fails (see
  PR14/#150's PR description for that verification).
- `feature_store/org_id={org}/daily_sales.parquet` and
  `models/org_id={org}/prophet_{product_id}.pkl` — per-org partitioning
  here also fixed a real pre-existing operability problem, not just a
  multi-tenancy concern: before Epoch 10, every `build_features()` call
  rewrote one single global file covering every product in the
  deployment, regardless of which org actually needed a refresh.
- MLflow's registered model name (`prophet_{product_id}`) deliberately
  does **not** bake in `organization_id` — `product_id` is already
  globally unique, so there's no collision risk in the registry
  namespace itself; only the *served* artifact's file path is org-scoped.

## IDOR: the recurring bug class this arc actually found

Several services had bare `.filter(Model.id == id)` lookups with zero
ownership check before being org-threaded — real, not hypothetical: a
user could read or mutate another org's row by guessing or enumerating
its id. Closed function-by-function across PR 9-11 (`recipe_service.py`,
`purchase_order_service.py`, `replay_service.py`), all following the
same shape: add `Model.organization_id == organization_id` to the
existing filter, and let the existing `XNotFoundError -> 404` convention
fire unchanged on a cross-org id. No new error class, no "wrong org" vs
"doesn't exist" signal ever leaks to the caller.

One fix was a genuine live data-destroying bug, not just an information
leak: `replay_service.rebuild_inventory_state()` used to do an
unfiltered `DELETE FROM inventory_state` before rebuilding — any org's
admin running replay wiped every other org's projection too. Fixed in
PR 11 (#147), with a direct regression test proving org 2's data
survives org 1 running replay.

A final repo-wide grep sweep (PR 16, #152) found three more bare
lookups in `inventory_service.py` (`get_inventory()`,
`_apply_event()`'s row-locked `InventoryState` fetch,
`_cascade_recipe_consumption()`'s `RecipeItem` fetch) — all three
**already safe by construction** (each is only ever reached after an
upstream `Product` lookup already confirmed the id belongs to the
caller's org, and `product_id`'s global uniqueness means there's no
second, cross-org row that query could have matched instead), not live
vulnerabilities. Given explicit filters anyway, matching this codebase's
"verify the invariant, don't just assume it" discipline rather than
leaving an implicit assumption undocumented in the code.

## Deliberately not org-scoped, and why

- `auth_service.authenticate_user()`'s `User` lookup is by `email`
  alone — correct, not a gap. `users.email` is globally unique by
  design (no org-selection step at login), so there's no
  `organization_id` to filter by until *after* the user is identified.
- `POST /api/inventory/export` (the REST route) stays reachable by any
  org's admin, even though the export operation itself is inherently
  whole-deployment (see "Analytics pipeline" above). PR 13 (#149)
  removed the equivalent *dashboard* button on purpose but deliberately
  left this API route alone — closing it too would have meant rewriting
  existing RBAC/audit-logging test coverage that wasn't part of that
  PR's scope. Flagged, not silently left; a reasonable follow-up if it
  ever matters in practice. Also documented in `SECURITY.md`'s auth
  model section — that file is the one a reader auditing access control
  is more likely to check first, and it previously said nothing about
  this specific gap.
- `app/scripts/build_features.py` / `train_model.py` (and therefore
  `scripts/retrain_cron.sh`) only ever build/train **org 1**. Both
  underlying service functions are genuinely org-scoped now (PR 15,
  #151); the CLI entry points just don't loop over every active org.
  Tracked as issue #171 — deferred because the right shape (a
  `--organization-id` flag per invocation, vs. auto-looping every active
  org) is a real design decision, not a mechanical fix.
- **Postgres Row-Level Security** as a *second*, DB-enforced isolation
  layer on top of the composite-FK design was explicitly scoped out of
  Epoch 10's exit criteria from the start (see ROADMAP.md) — the
  composite FKs already make cross-org references structurally
  impossible to *write*; RLS would additionally make cross-org rows
  structurally impossible to *read* even under an application bug that
  forgot an `organization_id` filter entirely. Same "code convention +
  DB backstop" pattern already used for `audit_log`'s tamper-protection
  trigger, just not applied here yet. A real hardening item for a later
  pass, not required for two orgs to safely coexist today.

## Testing

`tests/test_multi_tenancy.py` is the single home for cross-org isolation
tests — each PR that org-threaded a new route/service added its own
tests there rather than scattering them across feature-specific test
files, and PR 16 (#152) did a final consolidation pass closing gaps
individual PRs' narrower testing notes didn't require (e.g. PO
`receive`/`add_line`/`update_line`, `forecast`, and creation-time
rejection of a real cross-org supplier/product reference, not just
mutation-by-id). Shared builder helpers (`create_supplier`,
`create_draft_po`, `recipe_item`, webhook-signing helpers) live in
`tests/utils.py`, not duplicated per test file.

## How this was built

Epoch 10 was sequenced as 16 PRs (GitHub milestone "Epoch 10 —
Multi-Tenancy", issues #137-#152), one at a time, schema before write
path before services/API before the analytics pipeline. Every
org-scoped function defaults `organization_id` to `1` — a deliberate
staged-rollout shape, not a security fallback: it exists so a function
could be threaded before every one of its callers was updated in the
same PR, without breaking anything in between. By the end of the
sequence, every real caller passes it explicitly; the default is inert
in practice. See ROADMAP.md's Epoch 10 section for the full PR-by-PR
history and reasoning.
