# app/core/storage.py
"""Local-filesystem-or-S3 storage abstraction for the data pipeline.

The 4 pipeline roots (DATA_LAKE_ROOT, WAREHOUSE_ROOT, FEATURE_STORE_PATH,
MODELS_DIR) can each be a local path (default) or an s3:// URI. Every
function here dispatches on whether the given path looks like an S3 URI,
so call sites don't need their own local-vs-S3 branching.

Not covered here: the DuckDB catalog file (warehouse/*.duckdb) stays local
always — there's no supported way to run a writable DuckDB database
directly on S3, so it's rebuilt from S3-hosted source parquet each run
instead. See warehouse/ims_warehouse/profiles.yml and
app/services/warehouse_service.py's own S3 wiring for that piece.
"""

import posixpath
from pathlib import Path

import fsspec
import pandas as pd

from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    S3_ENDPOINT_URL,
    S3_URL_STYLE,
)


def is_s3(path: str) -> bool:
    return str(path).startswith("s3://")


def join(*parts: str) -> str:
    return posixpath.join(*(str(p) for p in parts))


def storage_options(path: str) -> dict:
    """s3fs/boto3 kwargs for the given path — empty dict for local paths,
    so passing this straight into pandas' storage_options= is always safe.
    """
    if not is_s3(path):
        return {}
    opts: dict = {}
    if AWS_ACCESS_KEY_ID:
        opts["key"] = AWS_ACCESS_KEY_ID
    if AWS_SECRET_ACCESS_KEY:
        opts["secret"] = AWS_SECRET_ACCESS_KEY
    client_kwargs: dict = {}
    if AWS_REGION:
        client_kwargs["region_name"] = AWS_REGION
    if S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = S3_ENDPOINT_URL
    if client_kwargs:
        opts["client_kwargs"] = client_kwargs
    if S3_URL_STYLE == "path":
        opts["config_kwargs"] = {"s3": {"addressing_style": "path"}}
    return opts


def mkdir(path: str) -> None:
    """No-op under S3 — object storage has no real directories, and
    writing an object creates its "prefix" implicitly."""
    if is_s3(path):
        return
    Path(path).mkdir(parents=True, exist_ok=True)


def exists(path: str) -> bool:
    fs, fs_path = fsspec.core.url_to_fs(path, **storage_options(path))
    return fs.exists(fs_path)


def cache_key(path: str) -> str:
    """A short string that changes whenever the object at path changes —
    ETag for S3 (content-hash-based), mtime/size fallback otherwise. For
    invalidating local read-through caches of remote files — see
    forecast_service.py's load_model()."""
    fs, fs_path = fsspec.core.url_to_fs(path, **storage_options(path))
    info = fs.info(fs_path)
    for key in ("ETag", "etag"):
        if info.get(key):
            return str(info[key]).strip('"')
    for key in ("LastModified", "mtime", "last_modified"):
        if info.get(key):
            return str(info[key])
    return str(info.get("size", ""))


def glob(root: str, pattern: str) -> list[str]:
    """Recursive glob under root, e.g. glob(INVENTORY_EVENTS_ROOT, "*.parquet").
    Returns full paths/URIs usable directly by read_parquet/open_read.
    """
    full_pattern = join(root, "**", pattern)
    fs, fs_pattern = fsspec.core.url_to_fs(full_pattern, **storage_options(root))
    matches = fs.glob(fs_pattern)
    if is_s3(root):
        return [f"s3://{m}" for m in matches]
    return matches


def open_read(path: str, mode: str = "r", **kwargs):
    """Context manager: `with open_read(path) as f: ...`"""
    return fsspec.open(path, mode, **storage_options(path), **kwargs)


def open_write(path: str, mode: str = "w", **kwargs):
    """Context manager: `with open_write(path) as f: ...`"""
    return fsspec.open(path, mode, **storage_options(path), **kwargs)


def to_parquet(df: pd.DataFrame, path: str, **kwargs) -> None:
    kwargs.setdefault("index", False)
    df.to_parquet(path, storage_options=storage_options(path), **kwargs)


def read_parquet(path: str, **kwargs) -> pd.DataFrame:
    return pd.read_parquet(path, storage_options=storage_options(path), **kwargs)


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def configure_duckdb_s3(conn) -> None:
    """Load DuckDB's httpfs extension and point it at the configured S3
    endpoint/credentials. Call once per connection before any
    read_parquet('s3://...')/write on it. No-op for anything not read from
    env config here — real AWS S3 doesn't need s3_endpoint/s3_url_style at
    all, only MinIO/self-hosted S3-compatible servers do.
    """
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    if AWS_REGION:
        conn.execute(f"SET s3_region={_sql_quote(AWS_REGION)}")
    if AWS_ACCESS_KEY_ID:
        conn.execute(f"SET s3_access_key_id={_sql_quote(AWS_ACCESS_KEY_ID)}")
    if AWS_SECRET_ACCESS_KEY:
        conn.execute(f"SET s3_secret_access_key={_sql_quote(AWS_SECRET_ACCESS_KEY)}")
    if S3_ENDPOINT_URL:
        # DuckDB's s3_endpoint wants host[:port], not a full URL with scheme.
        scheme, _, endpoint = S3_ENDPOINT_URL.partition("://")
        conn.execute(f"SET s3_endpoint={_sql_quote(endpoint)}")
        conn.execute(f"SET s3_use_ssl={'true' if scheme == 'https' else 'false'}")
    if S3_URL_STYLE == "path":
        conn.execute("SET s3_url_style='path'")
