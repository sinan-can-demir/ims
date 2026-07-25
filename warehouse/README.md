# Warehouse — Inventory Management System

## Overview

This directory contains the analytical layer of IMS, built on top of the
partitioned data lake using DuckDB.

The warehouse transforms raw inventory events into clean, queryable tables
following a star schema pattern.

---

## Data Flow
```
PostgreSQL (OLTP)
    ↓
data_lake/inventory_events/ (Parquet, partitioned by date)
    ↓
warehouse/ (star schema, analytical layer)
    ↓
Analytics / ML / Reporting
```

---

## Schema
```
dim_products ──────┐
                   ▼
dim_dates ────► fact_inventory_events
```

### fact_inventory_events
One row per inventory event. The central table for all analytical queries.

| Column | Type | Description |
|---|---|---|
| event_id | VARCHAR | Unique event identifier |
| product_id | INTEGER | FK to dim_products |
| date_id | VARCHAR | FK to dim_dates (YYYY-MM-DD) |
| event_type | VARCHAR | PURCHASE, SALE, DAMAGE, etc. |
| quantity | INTEGER | Normalized delta |
| created_at | TIMESTAMP | Original event timestamp |

### dim_products
One row per product.

| Column | Type | Description |
|---|---|---|
| product_id | INTEGER | Primary key |
| name | VARCHAR | Product name |
| sku | VARCHAR | Stock keeping unit |
| created_at | TIMESTAMP | When product was created |

### dim_dates
One row per calendar date. Pre-generated, not derived from events.

| Column | Type | Description |
|---|---|---|
| date_id | VARCHAR | Primary key — YYYY-MM-DD |
| year | INTEGER | |
| month | INTEGER | |
| day | INTEGER | |
| quarter | INTEGER | |
| day_of_week | VARCHAR | Monday, Tuesday, etc. |
| is_weekend | BOOLEAN | |

---

## How to Rebuild

Run export, then build the warehouse's dim/fact parquet files, then run the
dbt models on top of them, in order:
```bash
make export       # export events from Postgres to data_lake/
make warehouse    # build dimension and fact parquet files
make dbt-run      # build dbt models (warehouse/ims_warehouse/)
make dbt-test     # run dbt's schema tests
```

The warehouse files (including `ims.duckdb`, the dbt-managed database) are
derived artifacts and are not committed to git. They can always be rebuilt
from scratch using the commands above — this full chain also runs in CI
against a real Postgres (`.github/workflows/ci.yml`'s `pipeline` job).
See [`ims_warehouse/README.md`](ims_warehouse/README.md) for dbt-specific
details.

---

## Analytical Queries

See `warehouse/queries.sql` for documented query examples including:

- Daily inventory delta per product
- Event type breakdown
- Running inventory balance over time

---

## Design Principles

**Derived artifact.** Warehouse files are always rebuildable from the
event log. Never edit them manually.

**Star schema.** One central fact table, surrounded by dimension tables.
This pattern is optimized for analytical queries and is the foundation
of most business intelligence systems.

**DuckDB as query engine.** DuckDB reads Parquet files directly without
a loading step. The data_lake/ folder is the storage layer, DuckDB is
the query engine on top of it.