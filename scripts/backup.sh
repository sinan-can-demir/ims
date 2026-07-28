#!/usr/bin/env bash
#
# Backs up everything needed to reconstruct this IMS instance: the
# Postgres database (event log + every derived table) plus the local
# pipeline artifacts that only ever live on this filesystem — the gap
# docs/deployment/self-hosted.md's "What this doesn't cover yet" section
# used to flag. Artifact scope matches .gitignore's own definition of
# "generated, not tracked" (same paths make reset cleans up), not whole
# directories — data_lake/ and warehouse/ also hold git-tracked source
# (READMEs, the dbt project) that a restore shouldn't touch.
#
# Writes one timestamped archive; this script only writes locally,
# matching self-hosted.md's existing "copy it off the server on whatever
# schedule matters to you" framing — point <destination_dir> at a
# mounted network drive/synced folder, or wrap this in your own rsync,
# for real off-box durability.
#
# Usage:
#   scripts/backup.sh <destination_dir>
#
# Requires the `db` service to be up (docker compose up -d db).
# Linux/GNU tooling assumed, same as the rest of the self-hosted path.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}INFO:${NC} $1"; }
fail() { echo -e "${RED}FAIL:${NC} $1"; exit 1; }
pass() { echo -e "${GREEN}✓${NC} $1"; }

DEST_DIR="${1:-}"
if [[ -z "$DEST_DIR" ]]; then
  fail "Usage: $0 <destination_dir>"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# This script only ever operates on local disk — it has no S3 sync logic
# by design (see #22; ROADMAP.md scopes backup as explicitly non-S3 for
# the self-hosted case — bucket versioning plus a host-level backup of
# MinIO's own data volume covers that instead, not this script). Warn
# loudly instead of silently backing up nothing/stale local leftovers
# when a root is actually pointed at S3.
_resolve_var() {
  local var_name="$1" current="${!1:-}"
  if [[ -n "$current" ]]; then
    echo "$current"
    return
  fi
  [[ -f .env ]] && grep -E "^${var_name}=" .env 2>/dev/null | tail -1 | cut -d'=' -f2-
}

_s3_roots=()
for _var in DATA_LAKE_ROOT WAREHOUSE_ROOT FEATURE_STORE_PATH MODELS_DIR; do
  _value="$(_resolve_var "$_var")"
  [[ "$_value" == s3://* ]] && _s3_roots+=("$_var=$_value")
done

if [[ ${#_s3_roots[@]} -gt 0 ]]; then
  echo -e "${RED}WARNING:${NC} the following are configured as S3 URIs and will NOT be included in this backup (this script only covers local disk):"
  printf '  %s\n' "${_s3_roots[@]}"
  echo "For S3/MinIO durability, use bucket versioning and back up the MinIO data volume separately — see docs/deployment/self-hosted.md."
fi

mkdir -p "$DEST_DIR"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$WORK_DIR/data_lake" "$WORK_DIR/feature_store" "$WORK_DIR/warehouse" "$WORK_DIR/models"

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-ims}"

info "Dumping Postgres ($POSTGRES_DB)..."
# --clean --if-exists makes the dump self-contained: replaying it against
# an existing schema (the normal restore scenario — a fresh instance
# already has empty tables from `alembic upgrade head`) drops everything
# first instead of failing on "relation already exists".
docker compose exec -T db pg_dump -U "$POSTGRES_USER" --clean --if-exists "$POSTGRES_DB" \
  | gzip > "$WORK_DIR/postgres.sql.gz"

info "Copying local pipeline artifacts..."
if [[ -d data_lake/inventory_events ]]; then
  cp -r data_lake/inventory_events "$WORK_DIR/data_lake/"
fi
[[ -f data_lake/checkpoints.json ]] && cp data_lake/checkpoints.json "$WORK_DIR/data_lake/"
cp feature_store/*.parquet "$WORK_DIR/feature_store/" 2>/dev/null || true
cp warehouse/*.parquet "$WORK_DIR/warehouse/" 2>/dev/null || true
cp warehouse/*.duckdb "$WORK_DIR/warehouse/" 2>/dev/null || true
cp models/*.pkl "$WORK_DIR/models/" 2>/dev/null || true

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE_PATH="$DEST_DIR/ims-backup-${TIMESTAMP}.tar.gz"

tar -czf "$ARCHIVE_PATH" -C "$WORK_DIR" .

pass "Backup written to $ARCHIVE_PATH"
