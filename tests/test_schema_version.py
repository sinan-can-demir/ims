# tests/test_schema_version.py

from unittest.mock import patch

import pytest

from app.core import schema_version
from app.core.pipeline_state import load_json_marker


@pytest.fixture
def checkpoint_file(tmp_path):
    checkpoint = tmp_path / "checkpoints.json"
    with patch("app.core.schema_version.CHECKPOINT_FILE", checkpoint):
        yield checkpoint


def test_no_marker_is_treated_as_version_1_and_matches_default(checkpoint_file):
    """A fresh install with no checkpoints.json at all predates this system
    entirely — it's implicitly on the only schema that's ever existed."""
    with patch.object(schema_version, "DATA_LAKE_SCHEMA_VERSION", 1):
        schema_version.check_data_lake_schema_version("unused")

    assert not checkpoint_file.exists()


def test_matching_version_is_a_noop(checkpoint_file, tmp_path):
    checkpoint_file.write_text('{"schema_version": 1}')

    with patch.object(schema_version, "DATA_LAKE_SCHEMA_VERSION", 1):
        schema_version.check_data_lake_schema_version(str(tmp_path))

    assert load_json_marker(str(checkpoint_file))["schema_version"] == 1


def test_missing_migration_fails_loud(checkpoint_file, tmp_path):
    """A version gap with no registered migration must fail with a
    specific, actionable error — not a silent no-op or a generic crash."""
    checkpoint_file.write_text('{"schema_version": 1}')

    with (
        patch.object(schema_version, "DATA_LAKE_SCHEMA_VERSION", 2),
        patch.object(schema_version, "MIGRATIONS", {}),
    ):
        with pytest.raises(schema_version.SchemaVersionError, match="version 1.*version 2"):
            schema_version.check_data_lake_schema_version(str(tmp_path))


def test_downgrade_fails_loud(checkpoint_file, tmp_path):
    checkpoint_file.write_text('{"schema_version": 2}')

    with patch.object(schema_version, "DATA_LAKE_SCHEMA_VERSION", 1):
        with pytest.raises(schema_version.SchemaVersionError, match="downgrade"):
            schema_version.check_data_lake_schema_version(str(tmp_path))


def test_registered_migration_runs_and_updates_marker(checkpoint_file, tmp_path):
    checkpoint_file.write_text('{"schema_version": 1}')
    calls = []

    def fake_migrate(data_lake_root: str) -> None:
        calls.append(data_lake_root)

    with (
        patch.object(schema_version, "DATA_LAKE_SCHEMA_VERSION", 2),
        patch.object(schema_version, "MIGRATIONS", {(1, 2): fake_migrate}),
    ):
        schema_version.check_data_lake_schema_version(str(tmp_path))

    assert calls == [str(tmp_path)]
    assert load_json_marker(str(checkpoint_file))["schema_version"] == 2


def test_multi_step_chain_persists_progress_after_each_step(checkpoint_file, tmp_path):
    """If the 2nd of 2 migration steps fails, the marker must already
    reflect the 1st step's success — not silently re-run it, and not
    falsely claim the whole chain completed."""
    checkpoint_file.write_text('{"schema_version": 1}')

    def migrate_1_to_2(data_lake_root: str) -> None:
        pass

    def migrate_2_to_3(data_lake_root: str) -> None:
        raise RuntimeError("boom")

    with (
        patch.object(schema_version, "DATA_LAKE_SCHEMA_VERSION", 3),
        patch.object(
            schema_version,
            "MIGRATIONS",
            {(1, 2): migrate_1_to_2, (2, 3): migrate_2_to_3},
        ),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            schema_version.check_data_lake_schema_version(str(tmp_path))

    assert load_json_marker(str(checkpoint_file))["schema_version"] == 2
