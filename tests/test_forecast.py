# tests/test_forecast.py

import os
from unittest.mock import patch

import pandas as pd
import pytest

from app.services.forecast_service import forecast
from app.services.restock_service import get_restock_recommendation

from .utils import create_product


def test_restock_urgency_stockout(client, db):
    product = create_product(client)
    pid = product["id"]

    # Mock forecast so we don't need a trained model
    mock_forecast_df = pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [15.0] * 7,
            "yhat_lower": [10.0] * 7,
            "yhat_upper": [20.0] * 7,
        }
    )

    with patch("app.services.restock_service.forecast", return_value=mock_forecast_df):
        # current inventory is 0 — no events added
        result = get_restock_recommendation(db, pid)

    assert result["urgency"] == "STOCKOUT"
    assert result["current_inventory"] == 0


def test_restock_urgency_ok(client, db):
    product = create_product(client)
    pid = product["id"]

    # Add a large purchase so inventory is well above projected demand
    client.post(
        "/api/inventory/events",
        json={
            "product_id": pid,
            "event_type": "PURCHASE",
            "quantity": 500,
            "event_id": "evt-test-ok",
        },
    )

    mock_forecast_df = pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [15.0] * 7,  # projected demand = 105 total
            "yhat_lower": [10.0] * 7,
            "yhat_upper": [20.0] * 7,
        }
    )

    with patch("app.services.restock_service.forecast", return_value=mock_forecast_df):
        result = get_restock_recommendation(db, pid)

    assert result["urgency"] == "OK"
    assert result["current_inventory"] == 500
    assert result["recommended_order_qty"] == 0  # no order needed


def test_restock_clamps_negative_qty(client, db):
    product = create_product(client)
    pid = product["id"]

    # 1000 units in stock
    client.post(
        "/api/inventory/events",
        json={
            "product_id": pid,
            "event_type": "PURCHASE",
            "quantity": 1000,
            "event_id": "evt-test-clamp",
        },
    )

    # projected demand = 15 * 7 = 105 total
    # safety stock = 105 * 0.20 = 21
    # without clamp: 105 + 21 - 1000 = -874
    # with clamp: max(0, -874) = 0
    mock_forecast_df = pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [15.0] * 7,
            "yhat_lower": [10.0] * 7,
            "yhat_upper": [20.0] * 7,
        }
    )

    with patch("app.services.restock_service.forecast", return_value=mock_forecast_df):
        result = get_restock_recommendation(db, pid)

    # this is the core assertion — qty must never be negative
    assert result["recommended_order_qty"] >= 0
    assert result["recommended_order_qty"] == 0


_FEATURE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "feature_store", "org_id=1", "daily_sales.parquet"
)
_MODEL_FILE_8 = os.path.join(os.path.dirname(__file__), "..", "models", "org_id=1", "prophet_8.pkl")

_FEATURE_SKIP_REASON = "feature store not built — run make features"


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_feature_columns():
    df = pd.read_parquet(_FEATURE_FILE)
    expected = {
        "product_id",
        "date",
        "units_sold",
        "units_purchased",
        "net_delta",
        "rolling_avg_7d",
    }
    assert set(df.columns) == expected


@pytest.mark.skipif(not os.path.exists(_MODEL_FILE_8), reason="models not trained — run make train")
def test_forecast_returns_n_days():
    df = forecast(8, days=7)
    assert len(df) == 7


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_train_model_registers_to_mlflow(tmp_path, monkeypatch):
    pytest.importorskip("mlflow", reason="run `make train-deps` to install training dependencies")

    import app.services.forecast_service as forecast_service

    # Isolated model dir + registry so this test doesn't touch the real
    # models/ or mlflow.db, and doesn't collide with runs from `make train`.
    monkeypatch.setattr(forecast_service, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        forecast_service, "MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}"
    )
    monkeypatch.chdir(tmp_path)  # artifact store defaults to ./mlruns relative to cwd

    result = forecast_service.train_model(1)

    assert (tmp_path / "org_id=1" / "prophet_1.pkl").exists()
    assert result["mlflow_model_version"] == 1
    assert result["mae_in_sample"] >= 0

    import mlflow

    client = mlflow.MlflowClient()
    versions = client.search_model_versions("name='prophet_1'")
    assert len(versions) == 1
    assert versions[0].run_id == result["mlflow_run_id"]

    # Every train run auto-promotes to champion (not a review gate — see
    # docs/model-registry.md) so the registry reflects what's actually live.
    champion = client.get_model_version_by_alias("prophet_1", "champion")
    assert int(champion.version) == result["mlflow_model_version"]


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_rollback_model_restores_prior_version_and_champion(tmp_path, monkeypatch):
    pytest.importorskip("mlflow", reason="run `make train-deps` to install training dependencies")

    import mlflow

    import app.services.forecast_service as forecast_service

    monkeypatch.setattr(forecast_service, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        forecast_service, "MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}"
    )
    monkeypatch.chdir(tmp_path)

    first = forecast_service.train_model(1)
    second = forecast_service.train_model(1)
    assert second["mlflow_model_version"] == first["mlflow_model_version"] + 1

    # Second train run's file overwrote the first's — modification time
    # alone can't prove a rollback happened, so hash the artifact instead.
    import hashlib

    model_path = tmp_path / "org_id=1" / "prophet_1.pkl"
    after_second_train = hashlib.sha256(model_path.read_bytes()).hexdigest()

    result = forecast_service.rollback_model(1, first["mlflow_model_version"])
    assert result["version"] == first["mlflow_model_version"]

    after_rollback = hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert after_rollback != after_second_train

    client = mlflow.MlflowClient()
    champion = client.get_model_version_by_alias("prophet_1", "champion")
    assert int(champion.version) == first["mlflow_model_version"]


@pytest.mark.skipif(not os.path.exists(_FEATURE_FILE), reason=_FEATURE_SKIP_REASON)
def test_rollback_model_rejects_nonexistent_version(tmp_path, monkeypatch):
    pytest.importorskip("mlflow", reason="run `make train-deps` to install training dependencies")

    import app.services.forecast_service as forecast_service

    monkeypatch.setattr(forecast_service, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        forecast_service, "MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}"
    )
    monkeypatch.chdir(tmp_path)

    forecast_service.train_model(1)

    with pytest.raises(ValueError):
        forecast_service.rollback_model(1, 99999)


def test_forecast_endpoint_no_model(client):
    response = client.get("/api/forecast/99999")
    assert response.status_code == 404


@pytest.mark.parametrize("days", [0, -1, 91, 10_000])
def test_forecast_endpoint_rejects_out_of_range_days(client, days):
    response = client.get(f"/api/forecast/99999?days={days}")
    assert response.status_code == 422


def test_restock_endpoint_nonexistent_product(client):
    response = client.get("/api/forecast/restock/99999")
    assert response.status_code == 404


def test_restock_recommendation_nonexistent_product(db):
    with pytest.raises(Exception) as exc_info:
        get_restock_recommendation(db, 99999)
    assert getattr(exc_info.value, "status_code", None) == 404


# ---------------------------------------------------------------------------
# Day-of-week-aware forecasting — restaurant demand is weekday/weekend
# spiky, not flat like typical e-commerce SKU demand. These are empirical
# checks (real Prophet fits on synthetic data), not mocked, so they take a
# few seconds each — that's the point, they'd catch a real regression.
# ---------------------------------------------------------------------------


def _weekday_shaped_series(n_days, seed, shape=(0.8, 0.85, 0.95, 1.0, 1.3, 1.9, 1.4)):
    import numpy as np

    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-05", periods=n_days, freq="D")  # a Monday
    y = [max(1, 40 * shape[d.weekday()] + rng.normal(0, 5)) for d in dates]
    return pd.DataFrame({"ds": dates, "y": y})


def test_weekly_seasonality_beats_no_seasonality_on_restaurant_demand():
    """
    Backtested finding behind the _MIN_TRAINING_DAYS/weekly_seasonality
    comment in forecast_service.py: weekly_seasonality=True should
    meaningfully outperform leaving it off on day-of-week-shaped demand,
    given enough history. Guards against a future "simplification"
    quietly turning this off.
    """
    from prophet import Prophet

    df = _weekday_shaped_series(n_days=28, seed=7)
    train, test = df.iloc[:21], df.iloc[21:]

    def mae(model):
        pred = model.predict(test[["ds"]])
        # .to_numpy() — test["y"] and pred["yhat"] have different indexes
        # (test kept its original 21..27 index; predict() returns a fresh
        # 0-based one), so a plain Series subtraction would align by index
        # and silently produce all-NaN instead of a real per-row diff.
        return float(abs(test["y"].to_numpy() - pred["yhat"].to_numpy()).mean())

    with_weekly = Prophet(
        yearly_seasonality=False, weekly_seasonality=True, daily_seasonality=False
    )
    with_weekly.fit(train)

    without_weekly = Prophet(
        yearly_seasonality=False, weekly_seasonality=False, daily_seasonality=False
    )
    without_weekly.fit(train)

    assert mae(with_weekly) < mae(without_weekly) * 0.7


def test_train_model_rejects_data_below_min_training_days(tmp_path, monkeypatch):
    """
    At exactly the old 7-day minimum, weekly_seasonality=True can perform
    *worse* than off (backtested) — the model hasn't seen the weekly cycle
    repeat yet. train_model() now requires _MIN_TRAINING_DAYS (14).
    """
    import app.services.forecast_service as forecast_service

    df = _weekday_shaped_series(n_days=7, seed=1).rename(columns={"y": "units_sold"})
    df["date"] = df["ds"]
    df["product_id"] = 1
    org_dir = tmp_path / "org_id=1"
    org_dir.mkdir()
    df[["product_id", "date", "units_sold"]].to_parquet(org_dir / "daily_sales.parquet")

    monkeypatch.setattr(forecast_service, "FEATURE_STORE_PATH", tmp_path)

    with pytest.raises(ValueError, match="Need at least 14 days"):
        forecast_service.train_model(1)


def test_load_model_s3_cache_disambiguated_by_org(tmp_path, monkeypatch):
    """
    Epoch 10 PR 15 (#151): _MODEL_CACHE_DIR is one shared local temp
    directory across every org's requests in this process, not a
    per-org namespace the way MODELS_DIR itself now is — real collision
    is impossible (product_id is globally unique across orgs, so
    cache_key() already differs per org via the differing S3 model_path),
    but this proves the cache *filename* is disambiguated by org too, per
    the issue's own testing note. cache_key() is mocked to return the
    same value regardless of path specifically to isolate that — without
    organization_id in the filename, this would be a real collision.
    """
    import app.services.forecast_service as forecast_service

    monkeypatch.setattr(forecast_service, "_MODEL_CACHE_DIR", tmp_path)
    monkeypatch.setattr(forecast_service.storage, "is_s3", lambda path: True)
    monkeypatch.setattr(forecast_service.storage, "exists", lambda path: True)
    monkeypatch.setattr(forecast_service.storage, "cache_key", lambda path: "same-key-both-orgs")
    monkeypatch.setattr(forecast_service.joblib, "load", lambda f: "fake-model")

    class _FakeReadHandle:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def read(self):
            return b"fake-model-bytes"

    monkeypatch.setattr(forecast_service.storage, "open_read", lambda path, mode: _FakeReadHandle())

    forecast_service.load_model(1, organization_id=1)
    forecast_service.load_model(1, organization_id=2)

    cached_files = {p.name for p in tmp_path.glob("*.pkl")}
    assert len(cached_files) == 2
    assert any(name.startswith("prophet_1_1_") for name in cached_files)
    assert any(name.startswith("prophet_2_1_") for name in cached_files)
