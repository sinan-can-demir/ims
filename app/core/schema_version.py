# app/core/schema_version.py
"""Guards the shape of everything written under DATA_LAKE_ROOT.

The pipeline (export -> warehouse -> dbt -> features -> train) reads
parquet written by an earlier version of this app. If that app version
changed what gets written (a renamed or retyped column, a changed
partition layout), a stale on-disk schema surfaces 3 layers downstream as
a cryptic DuckDB "column not found" — see #210. This module turns that
into a loud, specific failure at the point of the actual mismatch, and
runs registered migrations to bring an old data lake up to date when one
exists for every step of the gap.
"""

from __future__ import annotations

from typing import Callable

from app.config import CHECKPOINT_FILE, DATA_LAKE_SCHEMA_VERSION
from app.core.logging import logger
from app.core.pipeline_state import load_json_marker, save_json_marker

SCHEMA_VERSION_KEY = "schema_version"

# (from_version, to_version) -> migrate(data_lake_root: str) -> None
# Populated by app/pipeline_migrations/ as real schema changes happen.
# Empty until the first one (schema version 2) is actually needed — see
# the 2a/2b split in #223.
MIGRATIONS: dict[tuple[int, int], Callable[[str], None]] = {}


class SchemaVersionError(RuntimeError):
    """Raised when the on-disk data lake can't be reconciled with the
    code's expected schema version — either no migration path exists, or
    the on-disk version is newer than the running code understands."""


def _get_on_disk_version() -> int:
    checkpoints = load_json_marker(CHECKPOINT_FILE)
    return checkpoints.get(SCHEMA_VERSION_KEY, 1)


def _set_on_disk_version(version: int) -> None:
    checkpoints = load_json_marker(CHECKPOINT_FILE)
    checkpoints[SCHEMA_VERSION_KEY] = version
    save_json_marker(CHECKPOINT_FILE, checkpoints)


def check_data_lake_schema_version(data_lake_root: str) -> None:
    """Reconcile the on-disk data lake with DATA_LAKE_SCHEMA_VERSION.

    No-op if they already match. Otherwise, walks the migration chain one
    step at a time, persisting the on-disk marker after each individual
    step succeeds — so a failure partway through a multi-step chain leaves
    an accurate resume point instead of a falsely-"fully migrated" marker
    or a silent re-run of already-applied steps.

    Raises SchemaVersionError (not caught here — callers, e.g.
    app/scripts/check_data_lake_schema.py, decide how to surface it) if
    the on-disk version is ahead of the code (a downgrade), or if any step
    of the required chain has no registered migration.
    """
    on_disk = _get_on_disk_version()
    target = DATA_LAKE_SCHEMA_VERSION

    if on_disk == target:
        return

    if on_disk > target:
        raise SchemaVersionError(
            f"data lake schema version {on_disk} is newer than this app "
            f"version supports (expects {target}). This looks like a "
            f"downgrade — refusing to run against it."
        )

    version = on_disk
    while version < target:
        step = (version, version + 1)
        migrate = MIGRATIONS.get(step)
        if migrate is None:
            raise SchemaVersionError(
                f"data lake schema is at version {on_disk}, code expects "
                f"version {target}, and no migration is registered for "
                f"step {step}. Add one in app/pipeline_migrations/ before "
                f"running the pipeline against this data lake."
            )
        logger.info(
            "data_lake_schema_migration_started",
            extra={"from_version": version, "to_version": version + 1},
        )
        migrate(data_lake_root)
        version += 1
        _set_on_disk_version(version)
        logger.info(
            "data_lake_schema_migration_completed",
            extra={"from_version": version - 1, "to_version": version},
        )
