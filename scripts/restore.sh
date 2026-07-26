#!/usr/bin/env bash
#
# Restores Postgres + local pipeline artifacts from a scripts/backup.sh
# archive. Destructive: replaces the current database and the same
# generated-artifact paths make reset cleans up (data_lake/inventory_events,
# data_lake/checkpoints.json, feature_store/*.parquet, warehouse/*.parquet,
# warehouse/*.duckdb, models/*.pkl) — not whole directories, so git-tracked
# source (READMEs, the dbt project under warehouse/ims_warehouse/) is left
# alone.
#
# Usage:
#   scripts/restore.sh <backup_archive.tar.gz>
#
# Requires the `db` service to be up (docker compose up -d db).

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}INFO:${NC} $1"; }
fail() { echo -e "${RED}FAIL:${NC} $1"; exit 1; }
pass() { echo -e "${GREEN}✓${NC} $1"; }

ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" ]]; then
  fail "Usage: $0 <backup_archive.tar.gz>"
fi
if [[ ! -f "$ARCHIVE" ]]; then
  fail "No such file: $ARCHIVE"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

info "Extracting $ARCHIVE..."
tar -xzf "$ARCHIVE" -C "$WORK_DIR"

if [[ ! -f "$WORK_DIR/postgres.sql.gz" ]]; then
  fail "$ARCHIVE doesn't look like a scripts/backup.sh archive (missing postgres.sql.gz)"
fi

echo "This will REPLACE the current database and local pipeline artifacts"
echo "(data_lake/inventory_events, feature_store/*.parquet, warehouse/*.parquet,"
echo "warehouse/*.duckdb, models/*.pkl) with the contents of:"
echo "  $ARCHIVE"
read -r -p "Continue? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
  fail "Aborted."
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-ims}"

info "Restoring Postgres ($POSTGRES_DB)..."
gunzip -c "$WORK_DIR/postgres.sql.gz" | docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB"

info "Restoring local pipeline artifacts..."
rm -rf "$PROJECT_ROOT/data_lake/inventory_events"
rm -f "$PROJECT_ROOT/data_lake/checkpoints.json"
rm -f "$PROJECT_ROOT"/feature_store/*.parquet
rm -f "$PROJECT_ROOT"/warehouse/*.parquet "$PROJECT_ROOT"/warehouse/*.duckdb
rm -f "$PROJECT_ROOT"/models/*.pkl

[[ -d "$WORK_DIR/data_lake/inventory_events" ]] &&
  cp -r "$WORK_DIR/data_lake/inventory_events" "$PROJECT_ROOT/data_lake/"
[[ -f "$WORK_DIR/data_lake/checkpoints.json" ]] &&
  cp "$WORK_DIR/data_lake/checkpoints.json" "$PROJECT_ROOT/data_lake/"
cp "$WORK_DIR"/feature_store/*.parquet "$PROJECT_ROOT/feature_store/" 2>/dev/null || true
cp "$WORK_DIR"/warehouse/*.parquet "$PROJECT_ROOT/warehouse/" 2>/dev/null || true
cp "$WORK_DIR"/warehouse/*.duckdb "$PROJECT_ROOT/warehouse/" 2>/dev/null || true
cp "$WORK_DIR"/models/*.pkl "$PROJECT_ROOT/models/" 2>/dev/null || true

pass "Restore complete."
