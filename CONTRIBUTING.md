# Contributing to IMS

Thanks for your interest — this started as a learning project and has grown into
an actively developed portfolio project, so contributions, questions, and issue
reports are all welcome. A few practical notes before you dive in.

## Getting set up

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

See the [README](README.md#getting-started) for running the full stack (Docker,
migrations, seeding data). For most code changes you only need the steps below.

## Running tests

```bash
make test          # unit + integration tests (SQLite in-memory by default)
```

The concurrency-critical tests (e.g. oversell protection, which relies on
`SELECT FOR UPDATE`) are marked `@pytest.mark.postgres` and are skipped unless
`TEST_DATABASE_URL` points at a real Postgres instance — SQLite silently ignores
row locking, so that path can't be verified against it. To run the full suite
locally:

```bash
docker run -d -p 5433:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=ims_test postgres:15
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/ims_test make test
```

CI runs both lanes automatically (see `.github/workflows/ci.yml`), so this is
optional locally but useful if you're touching `inventory_service.py`.

`make test-e2e` runs the bash-based end-to-end suite and needs the full Docker
stack (`make up`) running first.

## Data pipeline / dbt changes

If you're touching `app/scripts/export_events.py`, `build_warehouse.py`, or
anything under `warehouse/ims_warehouse/models/`, exercise the full chain
locally against a real Postgres before opening a PR — CI does the same
thing (`.github/workflows/ci.yml`'s `pipeline` job) and will catch it either
way, but it's faster to find locally:

```bash
alembic upgrade head
python scripts/seed_data.py
make export
make warehouse
make dbt-run
make dbt-test
```

`profiles.yml` is committed under `warehouse/ims_warehouse/` (no secrets —
duckdb has none), so this works on a fresh clone with no extra setup. See
[`warehouse/README.md`](warehouse/README.md) for the full pipeline.

## Linting and formatting

```bash
make lint           # ruff check .
make format          # ruff format .
```

CI enforces both `ruff check` and `ruff format --check`. Run `make format`
before committing if you're not sure your changes conform.

## Branches and PRs

- Branch from `main`, open a PR back into `main`.
- Keep PRs focused — one logical change per PR is easier to review than a
  bundle of unrelated fixes.
- Make sure `make test` and `make lint` pass before requesting review; CI will
  also check this.
- If you're picking up planned work, check [`ROADMAP.md`](ROADMAP.md) first so
  effort isn't duplicated — it tracks what's done, in progress, and planned by
  epoch.

## Reporting bugs / security issues

- Regular bugs: open a GitHub issue using the bug report template.
- Security vulnerabilities: see [`SECURITY.md`](SECURITY.md) — please don't
  file those as public issues.
