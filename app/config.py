# app/config.py

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------
# Data Lake
# -----------------
# Plain strings, not Path objects — each of these 4 roots can be either a
# local filesystem path (default) or an s3:// URI, dispatched at each call
# site via app/core/storage.py. Path("s3://bucket/key") would mangle the
# URI as if it were a local relative path, so these can't stay Path-typed.
DATA_LAKE_ROOT = os.getenv("DATA_LAKE_ROOT", str(BASE_DIR / "data_lake"))
INVENTORY_EVENTS_ROOT = f"{DATA_LAKE_ROOT.rstrip('/')}/inventory_events"
CHECKPOINT_FILE = f"{DATA_LAKE_ROOT.rstrip('/')}/checkpoints.json"

# ------------------
# Warehouse
# ------------------
WAREHOUSE_ROOT = os.getenv("WAREHOUSE_ROOT", str(BASE_DIR / "warehouse"))
WAREHOUSE_START_DATE = os.getenv("WAREHOUSE_START_DATE", "2020-01-01")
WAREHOUSE_END_DATE = os.getenv("WAREHOUSE_END_DATE", "2030-12-31")

# -------------------
# Feature
# -------------------
FEATURE_STORE_PATH = os.getenv("FEATURE_STORE_PATH", str(BASE_DIR / "feature_store"))
MODELS_DIR = os.getenv("MODELS_DIR", str(BASE_DIR / "models"))

# -------------------------
# S3-compatible object storage (optional)
# -------------------------
# Unset by default — the 4 roots above stay on local disk unless pointed at
# an s3:// URI. When they are, these credentials/endpoint config apply.
# Leave S3_ENDPOINT_URL unset for real AWS S3; set it for MinIO/any other
# S3-compatible self-hosted endpoint. See app/core/storage.py.
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.getenv("AWS_REGION", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
# "path" for MinIO/most self-hosted S3-compatible servers (bucket in the URL
# path); unset/"vhost" for real AWS S3 (bucket in the hostname, the default).
S3_URL_STYLE = os.getenv("S3_URL_STYLE", "")

# -------------------------
# Model Registry (MLflow)
# -------------------------
# SQLite-backed by default (single file, no server to run) — MLflow's plain
# filesystem store is in maintenance mode and no longer supports the model
# registry. Requires `pip install -r requirements-train.txt`; not part of
# the API image (see docs/model-registry.md).
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{BASE_DIR / 'mlflow.db'}")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "prophet-demand-forecasting")
