# app/services/forecast_service.py

from pathlib import Path

import joblib
import pandas as pd
from prophet import Prophet

from app.config import FEATURE_STORE_PATH, MLFLOW_EXPERIMENT_NAME, MLFLOW_TRACKING_URI, MODELS_DIR
from app.core.logging import logger

# app.config exports these as plain strings (so an s3:// URI doesn't get
# mangled by Path), but this file hasn't been migrated to
# app.core.storage yet (see #22) — wrap back to Path here so existing
# local-mode behavior stays exactly as it was.
FEATURE_STORE_PATH = Path(FEATURE_STORE_PATH)
MODELS_DIR = Path(MODELS_DIR)

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


def _ensure_directories() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    FEATURE_STORE_PATH.mkdir(exist_ok=True)


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

    return {
        "mlflow_run_id": run.info.run_id,
        "mlflow_model_version": model_info.registered_model_version,
    }


def train_model(product_id: int) -> dict:
    """
    Train a Prophet demand forecasting model for a single product.
    Saves the model to models/prophet_{product_id}.pkl.
    Returns training summary metadata.
    """
    _ensure_directories()

    logger.info("model_training_started", extra={"product_id": product_id})

    # 1. Load features for this product
    df = pd.read_parquet(FEATURE_STORE_PATH / "daily_sales.parquet")
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

    # 4. Save the model to disk (unchanged serving path — forecast()/load_model()
    #    keep reading this file regardless of the registry below)
    model_path = MODELS_DIR / f"prophet_{product_id}.pkl"
    joblib.dump(model, model_path)

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


def train_all_models() -> list[dict]:
    """Train a model for every product in the feature store."""

    df = pd.read_parquet(FEATURE_STORE_PATH / "daily_sales.parquet")
    product_ids = df["product_id"].unique().tolist()

    return [train_model(pid) for pid in product_ids]


def load_model(product_id: int) -> Prophet:
    """Load a trained model from disk. Raises if not found."""
    _ensure_directories()

    model_path = MODELS_DIR / f"prophet_{product_id}.pkl"
    if not model_path.exists():
        raise FileNotFoundError(
            f"No trained model found for product {product_id}. Run make train first."
        )
    return joblib.load(model_path)


def forecast(product_id: int, days: int = 7) -> pd.DataFrame:
    """
    Load the trained model for a product and generate a forecast.
    Returns a DataFrame with columns: ds, yhat, yhat_lower, yhat_upper.
    """
    _ensure_directories()

    logger.info("forecast_started", extra={"product_id": product_id, "days": days})

    model = load_model(product_id)

    # Prophet requires a future DataFrame with 'ds' column
    future = model.make_future_dataframe(periods=days)
    prediction = model.predict(future)

    logger.info("forecast_completed", extra={"product_id": product_id})

    # Return only the future rows (not historical)
    return prediction[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(days)
