#!/usr/bin/env bash
#
# Wraps `make features && make train` for unattended, scheduled retraining
# via host cron — see docs/deployment/self-hosted.md's "Automated
# retraining" section for a crontab example. Scoped as a plain cron
# wrapper around the existing Makefile targets rather than a new
# scheduler/worker service: no scheduling infrastructure exists anywhere
# in this codebase, and at this project's actual scale (a handful of
# products) that's proportionate — see ROADMAP.md's Epoch 9 section.
#
# Every run immediately overwrites every product's live-serving model —
# see docs/model-registry.md's "Automated retraining" section. There is no
# review gate; `python -m app.scripts.rollback_model` is the fix if a bad
# retrain needs undoing, not a pre-emptive approval step on every run.
#
# Requires training dependencies already installed (`make train-deps`) and
# the feature store buildable (a real Postgres reachable at DATABASE_URL,
# `make export` already run at least once) — same preconditions as running
# `make features`/`make train` by hand.
#
# Usage:
#   scripts/retrain_cron.sh
#
# Example crontab line (daily at 3am, output appended to a log file):
#   0 3 * * * cd /path/to/ims-manual && scripts/retrain_cron.sh >> /var/log/ims-retrain.log 2>&1

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting scheduled retrain..."

make features
make train

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Retrain complete."
