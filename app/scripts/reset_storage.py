# app/scripts/reset_storage.py
#
# The S3-aware half of `make reset` — the Makefile's own `rm -rf` commands
# only ever touch local disk, so any of the 4 pipeline roots actually
# pointed at s3:// would silently keep their old data across a reset,
# breaking the clean-slate guarantee `make reset` exists for (stale
# checkpoints skip freshly seeded events; old rows with now-colliding IDs
# break dbt's uniqueness test). No-op for any root that's local.

from app.config import DATA_LAKE_ROOT, FEATURE_STORE_PATH, MODELS_DIR, WAREHOUSE_ROOT
from app.core import storage


def main() -> None:
    for root in (DATA_LAKE_ROOT, WAREHOUSE_ROOT, FEATURE_STORE_PATH, MODELS_DIR):
        if storage.is_s3(root):
            print(f"Clearing {root}...")
            storage.rmtree(root)


if __name__ == "__main__":
    main()
