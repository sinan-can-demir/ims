# app/pipeline_migrations/
"""Data lake schema migrations, one module per version transition.

Convention: a `v{N}_to_v{N+1}.py` module exposing

    def migrate(data_lake_root: str) -> None: ...

that walks the partitioned parquet tree under data_lake_root
(org_id=/year=/month=/day=/*.parquet — see
app/services/export_service.py's _write_partitioned_parquet) and rewrites
each file into the new shape, using app/core/storage.py's read/write
helpers so it stays S3-compatible.

Register the transition in app/core/schema_version.py's MIGRATIONS dict.
Empty until the first one (schema version 2) is actually needed.
"""
