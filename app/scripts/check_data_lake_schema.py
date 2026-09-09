# app/scripts/check_data_lake_schema.py
#
# Prerequisite of both `make warehouse` and `make dbt-run` (see Makefile) —
# they're two independent entry points that read data_lake/ directly
# (one via Python, one via a separate `dbt` CLI invocation that can't run a
# Python pre-check inline), so the guard has to run ahead of both rather
# than live inside either one. See app/core/schema_version.py for #210.

import sys

from app.config import DATA_LAKE_ROOT
from app.core.schema_version import SchemaVersionError, check_data_lake_schema_version


def main() -> None:
    try:
        check_data_lake_schema_version(DATA_LAKE_ROOT)
    except SchemaVersionError as exc:
        print(f"data lake schema check failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
