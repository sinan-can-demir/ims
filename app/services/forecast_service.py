# app/services/forecast_service.py

import hashlib
import tempfile
from pathlib import Path

import joblib
import pandas as pd
from prophet import Prophet

from app.config import FEATURE_STORE_PATH, MLFLOW_EXPERIMENT_NAME, MLFLOW_TRACKING_URI, MODELS_DIR
from app.core import storage
from app.core.logging import logger

# Local write-through cache for load_model() (the live-serving path only —
# train_model()'s save always goes straight to storage). Avoids a network
# round-trip to S3 on every forecast request; see load_model() for the
# cache-key-based invalidation that picks up a retrain.
_MODEL_CACHE_DIR = Path(tempfile.gettempdir()) / "ims_model_cache"

# Backtested against restaurant-shaped synthetic demand (weekday/weekend
# spikes, including a sharp single-day-spike shape): at exactly 7 days
# (the old minimum), weekly_seasonality=True can perform *worse* than
# leaving it off — the model hasn't seen the weekly cycle repeat yet, so
# it has nothing to distinguish a real day-of-week effect from one week's
# noise. From ~10 days on, weekly_seasonality=True reliably wins by a wide
# margin (3-4x lower MAE by 14+ days) and higher Fourier orders /
# explicit day-of-week regressors add no measurable benefit over Prophet's
# default — see tests/test_forecast.py::test_weekly_seasonality_*.
_MIN_TRAINING_DAYS = 14


def _ensure_directories(organization_id: int) -> None:
    storage.mkdir(storage.join(MODELS_DIR, f"org_id={organization_id}"))
    storage.mkdir(storage.join(FEATURE_STORE_PATH, f"org_id={organization_id}"))


def _log_run_to_mlflow(
    product_id: int, model: Prophet, prophet_df: pd.DataFrame, mae: float, mape_pct: float | None
) -> dict:
    """
    Log the training run, its metrics, and the model artifact to the MLflow
    model registry (registered model name: prophet_{product_id}). See
    docs/model-registry.md for promotion/rollback.
    """
    try:
        import mlflow
        import mlflow.prophet
    except ImportError as e:
        raise ImportError(
            "mlflow is required to train models. Install training dependencies with: "
            "pip install -r requirements-train.txt"
        ) from e

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    with mlflow.start_run(run_name=f"prophet_{product_id}") as run:
        mlflow.set_tag("product_id", product_id)
        mlflow.log_params(
            {
                "yearly_seasonality": model.yearly_seasonality,
                "weekly_seasonality": model.weekly_seasonality,
                "daily_seasonality": model.daily_seasonality,
                "interval_width": model.interval_width,
            }
        )
        mlflow.log_metric("training_rows", len(prophet_df))
        mlflow.log_metric("mae_in_sample", mae)
        if mape_pct is not None:
            mlflow.log_metric("mape_in_sample_pct", mape_pct)

        model_info = mlflow.prophet.log_model(
            model,
            name="model",
            registered_model_name=f"prophet_{product_id}",
        )

        # Every training run's model immediately becomes what's served (see
        # train_model()'s unconditional file write below) — set champion to
        # match so the registry accurately reflects "what's currently
        # live." This is a rollback reference point, not a review gate —
        # training was already unconditionally promoting before this alias
        # existed; this just makes the registry tell the truth about it.
        # See docs/model-registry.md and rollback_model() below.
        mlflow.MlflowClient().set_registered_model_alias(
            f"prophet_{product_id}", "champion", model_info.registered_model_version
        )

    return {
        "mlflow_run_id": run.info.run_id,
        "mlflow_model_version": model_info.registered_model_version,
    }


def train_model(product_id: int, organization_id: int = 1) -> dict:
    """
    Train a Prophet demand forecasting model for a single product.
    Saves the model to models/org_id={organization_id}/prophet_{product_id}.pkl.
    Returns training summary metadata.

    MLflow's registered model name (prophet_{product_id}) deliberately
    does NOT bake in organization_id — product_id is already globally
    unique across every org (see ROADMAP.md's Epoch 10 section), so
    there's zero collision risk in the registry namespace.
    """
    _ensure_directories(organization_id)

    logger.info(
        "model_training_started",
        extra={"product_id": product_id, "organization_id": organization_id},
    )

    # 1. Load features for this product
    df = storage.read_parquet(
        storage.join(FEATURE_STORE_PATH, f"org_id={organization_id}", "daily_sales.parquet")
    )
    product_df = df[df["product_id"] == product_id].copy()

    if len(product_df) < _MIN_TRAINING_DAYS:
        raise ValueError(
            f"Product {product_id} has only {len(product_df)} days of data. "
            f"Need at least {_MIN_TRAINING_DAYS} days (two full weeks) to train — "
            "see the _MIN_TRAINING_DAYS comment above for why 7 wasn't enough."
        )

    # 2. Format for Prophet — requires 'ds' and 'y' columns. Reset the index
    #    (still carrying product_df's original row numbers after the filter
    #    above) so it aligns with model.predict()'s 0..n-1 output below.
    prophet_df = product_df.rename(columns={"date": "ds", "units_sold": "y"})[["ds", "y"]]
    prophet_df = prophet_df.reset_index(drop=True)

    prophet_df["ds"] = pd.to_datetime(prophet_df["ds"])

    # 3. Train the model
    model = Prophet(
        yearly_seasonality=False,  # not enough data for yearly patterns yet
        # Empirically validated (not just assumed) for day-of-week-heavy
        # demand like a restaurant's — see _MIN_TRAINING_DAYS above.
        # Prophet's default Fourier order already captures a day-of-week
        # pattern about as well as a higher order or explicit per-weekday
        # regressors would, so we don't add that complexity.
        weekly_seasonality=True,
        daily_seasonality=False,
        interval_width=0.95,  # 95% confidence intervals on predictions
    )
    model.fit(prophet_df)

    # 4. Save the model (unchanged serving path — forecast()/load_model()
    #    keep reading this file regardless of the registry below). joblib
    #    doesn't understand s3:// URIs natively — needs an actual file
    #    handle, unlike the pandas to_parquet/read_parquet calls elsewhere.
    model_path = storage.join(MODELS_DIR, f"org_id={organization_id}", f"prophet_{product_id}.pkl")
    with storage.open_write(model_path, "wb") as f:
        joblib.dump(model, f)

    # 5. In-sample fit quality — cheap to compute, useful signal for the
    #    registry; not a substitute for held-out backtesting
    in_sample = model.predict(prophet_df[["ds"]])
    residuals = (prophet_df["y"] - in_sample["yhat"]).abs()
    mae = float(residuals.mean())
    nonzero = prophet_df["y"] != 0
    mape_pct = (
        float((residuals[nonzero] / prophet_df["y"][nonzero]).mean() * 100)
        if nonzero.any()
        else None
    )

    # 6. Register the model + log metrics to MLflow
    mlflow_info = _log_run_to_mlflow(product_id, model, prophet_df, mae, mape_pct)

    logger.info(
        "model_training_completed",
        extra={
            "product_id": product_id,
            "training_rows": len(prophet_df),
            "model_path": str(model_path),
            "mae_in_sample": mae,
            **mlflow_info,
        },
    )

    return {
        "product_id": product_id,
        "training_rows": len(prophet_df),
        "model_path": str(model_path),
        "mae_in_sample": mae,
        **mlflow_info,
    }


def train_all_models(organization_id: int = 1) -> list[dict]:
    """Train a model for every product in this org's feature store."""

    df = storage.read_parquet(
        storage.join(FEATURE_STORE_PATH, f"org_id={organization_id}", "daily_sales.parquet")
    )
    product_ids = df["product_id"].unique().tolist()

    return [train_model(pid, organization_id) for pid in product_ids]


def rollback_model(product_id: int, version: int, organization_id: int = 1) -> dict:
    """
    Roll back a product's live-serving model to a specific prior MLflow
    registry version — the missing half of docs/model-registry.md's
    versioning story (the registry has tracked every run since day one;
    there was no way to act on that until this function). Overwrites
    models/org_id={organization_id}/prophet_{product_id}.pkl (the exact
    file load_model() reads) with that version's artifact, and re-points
    the champion alias so the registry stays consistent with what's
    actually live.
    """
    try:
        import mlflow
        import mlflow.prophet
    except ImportError as e:
        raise ImportError(
            "mlflow is required to roll back models. Install training dependencies with: "
            "pip install -r requirements-train.txt"
        ) from e

    _ensure_directories(organization_id)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    registered_name = f"prophet_{product_id}"
    client = mlflow.MlflowClient()

    try:
        client.get_model_version(registered_name, str(version))
    except mlflow.exceptions.MlflowException as e:
        raise ValueError(f"No version {version} found for '{registered_name}'") from e

    model = mlflow.prophet.load_model(f"models:/{registered_name}/{version}")

    model_path = storage.join(MODELS_DIR, f"org_id={organization_id}", f"prophet_{product_id}.pkl")
    with storage.open_write(model_path, "wb") as f:
        joblib.dump(model, f)

    client.set_registered_model_alias(registered_name, "champion", version)

    logger.info(
        "model_rollback_completed",
        extra={
            "product_id": product_id,
            "version": version,
            "organization_id": organization_id,
            "model_path": str(model_path),
        },
    )

    return {"product_id": product_id, "version": version, "model_path": str(model_path)}


def load_model(product_id: int, organization_id: int = 1) -> Prophet:
    """Load a trained model. Raises if not found.

    For local paths, reads directly. For S3 paths, checks a local
    write-through cache first (avoiding a network round-trip on every
    forecast request) — cache_key() changes whenever the underlying S3
    object changes, so a retrain automatically invalidates the old entry
    (new key -> new cache filename -> cache miss -> refetch). The cache
    filename includes organization_id too — _MODEL_CACHE_DIR is a shared
    local temp directory across every org's requests in this process, not
    a per-org namespace like MODELS_DIR itself is.
    """
    _ensure_directories(organization_id)

    model_path = storage.join(MODELS_DIR, f"org_id={organization_id}", f"prophet_{product_id}.pkl")
    if not storage.exists(model_path):
        raise FileNotFoundError(
            f"No trained model found for product {product_id}. Run make train first."
        )

    if not storage.is_s3(model_path):
        with storage.open_read(model_path, "rb") as f:
            return joblib.load(f)

    key = storage.cache_key(model_path)
    _MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
    cache_file = _MODEL_CACHE_DIR / f"prophet_{organization_id}_{product_id}_{key_hash}.pkl"

    if not cache_file.exists():
        with storage.open_read(model_path, "rb") as f:
            cache_file.write_bytes(f.read())

    with cache_file.open("rb") as f:
        return joblib.load(f)


def forecast(product_id: int, days: int = 7, organization_id: int = 1) -> pd.DataFrame:
    """
    Load the trained model for a product and generate a forecast.
    Returns a DataFrame with columns: ds, yhat, yhat_lower, yhat_upper.
    """
    _ensure_directories(organization_id)

    logger.info(
        "forecast_started",
        extra={"product_id": product_id, "days": days, "organization_id": organization_id},
    )

    model = load_model(product_id, organization_id)

    # Prophet requires a future DataFrame with 'ds' column
    future = model.make_future_dataframe(periods=days)
    prediction = model.predict(future)

    logger.info("forecast_completed", extra={"product_id": product_id})

    # Return only the future rows (not historical)
    return prediction[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(days)
