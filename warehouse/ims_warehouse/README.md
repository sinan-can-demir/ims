# ims_warehouse (dbt project)

See [`warehouse/README.md`](../README.md) for the full data flow (PostgreSQL
→ Parquet data lake → this dbt project → analytics/ML/dashboard) and how to
rebuild the warehouse from scratch.

## Running dbt

From the repo root, use the Makefile targets — they run against real data
and are exercised in CI (`.github/workflows/ci.yml`'s `pipeline` job):

```bash
make dbt-run    # build the dim/fact models
make dbt-test   # run the schema tests (unique, not_null, relationships)
```

If you're running `dbt` directly instead, pass `--profiles-dir .` from
inside this directory — `profiles.yml` is committed here (no secrets, just
a local DuckDB file path) rather than relying on `~/.dbt/profiles.yml`, so
this works the same on a fresh clone and in CI with no per-machine setup:

```bash
cd warehouse/ims_warehouse
dbt run --profiles-dir .
dbt test --profiles-dir .
```

### Resources
- [dbt docs](https://docs.getdbt.com/docs/introduction)
- [dbt Discourse](https://discourse.getdbt.com/)
- [dbt community Slack](https://community.getdbt.com/)
