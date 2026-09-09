# app/core/pipeline_state.py
"""Generic JSON marker-file read/write, shared by every pipeline module that
needs to persist small bits of state (export checkpoints, schema version,
...) under DATA_LAKE_ROOT. Works under both local disk and S3 via
app/core/storage.py, same as the rest of the pipeline.
"""

import json
import posixpath
from typing import Any

from app.core import storage


def load_json_marker(path: str) -> dict[str, Any]:
    """Read a JSON marker file, returning {} if it doesn't exist yet."""
    if not storage.exists(path):
        return {}
    with storage.open_read(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_marker(path: str, data: dict[str, Any]) -> None:
    """Write a JSON marker file, creating its parent directory first."""
    storage.mkdir(posixpath.dirname(path))
    with storage.open_write(path, encoding="utf-8") as f:
        json.dump(data, f, indent=2)
