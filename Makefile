# 📦 IMS Makefile

.PHONY: up down reset rebuild logs seed export warehouse dbt-run dbt-test dbt-docs \
        features train train-deps test test-e2e test-all test-clean migrate shell dashboard lint format \
        desktop-dev desktop-build desktop-sign desktop-release

# Prefer the project's own venv so these don't silently break (dbt/joblib
# "not found") when it exists but isn't activated — but fall back to bare
# commands when there's no venv at all, e.g. in CI, which installs
# dependencies straight into the runner's Python with no .venv/ present.
ifneq ($(wildcard .venv/bin/python),)
    PYTHON    := $(CURDIR)/.venv/bin/python
    DBT       := $(CURDIR)/.venv/bin/dbt
    PYTEST    := $(CURDIR)/.venv/bin/pytest
    RUFF      := $(CURDIR)/.venv/bin/ruff
    STREAMLIT := $(CURDIR)/.venv/bin/streamlit
else
    PYTHON    := python3
    DBT       := dbt
    PYTEST    := pytest
    RUFF      := ruff
    STREAMLIT := streamlit
endif

# docker-compose.yml lives in deploy/ now, not repo root — Compose defaults
# to treating the *first* -f file's directory as the "project directory"
# (resolves build context, bind mounts, and .env interpolation against it),
# which would silently become deploy/ instead of repo root, and would also
# rename the Compose project itself (deploy_* container/volume names)
# instead of matching what pre-existing deployments already have. Pinning
# --project-directory . keeps both exactly as they were when the file lived
# at repo root.
COMPOSE := docker compose -f deploy/docker-compose.yml --project-directory .

# -------------------------
# Dev lifecycle
# -------------------------
up:
	$(COMPOSE) up

up-d:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

# data_lake/, feature_store/, warehouse/, and models/ are local files, not
# Docker volumes — `down -v` wipes the DB but leaves these stale. A stale
# checkpoint.json in particular makes the next `make export` skip freshly
# seeded events (it resumes from the old high-water mark) while old rows
# with now-colliding IDs stay in the parquet files, breaking the dbt
# uniqueness test and starving the feature store. Clear them so a reset
# always starts every downstream stage from a clean slate.
reset:
	$(COMPOSE) down -v
	rm -rf data_lake/inventory_events/* data_lake/checkpoints.json
	rm -f feature_store/*.parquet
	rm -f warehouse/*.parquet warehouse/ims.duckdb
	rm -f models/*.pkl
	$(PYTHON) -m app.scripts.reset_storage
	$(COMPOSE) up --build

rebuild:
	$(COMPOSE) up --build

logs:
	$(COMPOSE) logs -f

# -------------------------
# Application layer
# -------------------------
dashboard:
	$(STREAMLIT) run dashboard/app.py

# -------------------------
# Database
# -------------------------
migrate:
	$(COMPOSE) run --rm migrate

# -------------------------
# Seed data
# -------------------------
seed:
	$(PYTHON) scripts/seed_data.py

# -------------------------
# Export events
# -------------------------
export:
	$(PYTHON) -m app.scripts.export_events

# -------------------------
# Warehouse
# -------------------------
warehouse:
	$(PYTHON) -m app.scripts.build_warehouse

# -------------------------
# dbt
# -------------------------
# --profiles-dir . points at the profiles.yml committed alongside this
# project instead of the ~/.dbt/ default, so this works on a fresh clone
# and in CI without any per-machine setup.
dbt-run:
	cd warehouse/ims_warehouse && $(DBT) run --profiles-dir .

dbt-test:
	cd warehouse/ims_warehouse && $(DBT) test --profiles-dir .

dbt-docs:
	cd warehouse/ims_warehouse && $(DBT) docs generate --profiles-dir . && $(DBT) docs serve --profiles-dir .

# -------------------------
# Features
# -------------------------
features:
	$(PYTHON) -m app.scripts.build_features

# -------------------------
# Train
# -------------------------
# One-off: installs mlflow-skinny on top of requirements.txt so `make train`
# can log to the model registry. Not part of `make up`/the API image.
train-deps:
	$(PYTHON) -m pip install -r requirements-train.txt

train:
	$(PYTHON) -m app.scripts.train_model

# -------------------------
# Shell access
# -------------------------
shell:
	$(COMPOSE) exec api sh

# -------------------------
# Pytest (fast tests)
# -------------------------
test:
	$(PYTEST)

# -------------------------
# E2E System Test (Docker)
# -------------------------
test-e2e:
	sh test_scripts/test_sc.sh

# -------------------------
# Full pipeline
# -------------------------
test-all:
	make test
	make test-e2e

# -------------------------
# Cleanup
# -------------------------
test-clean:
	rm -rf .pytest_cache

# -------------------------
# Lint / format
# -------------------------
lint:
	$(RUFF) check .

format:
	$(RUFF) format .

# -------------------------
# Desktop app (Linux native installer, see desktop/README.md)
# -------------------------
desktop-dev:
	cd desktop && npm run tauri dev

desktop-build:
	cd desktop && npm run tauri build

# Finds the most recently built .rpm rather than hardcoding a version, so
# this doesn't need editing every release. Signing is a manual, local-only
# step on purpose (see #213) -- prompts for the GPG passphrase, no CI
# automation, no private key anywhere but the maintainer's own machine.
desktop-sign:
	./desktop/sign-release.sh "$$(ls -t desktop/src-tauri/target/release/bundle/rpm/*.rpm | head -1)"

# Chains build -> sign, matching how `test-all` already chains test -> test-e2e.
desktop-release:
	make desktop-build
	make desktop-sign