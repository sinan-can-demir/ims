# tests/test_fleet_service.py

from unittest.mock import patch

import pandas as pd

from app.services.fleet_service import get_fleet_status

from .utils import create_product, purchase


def test_fleet_status_empty(db):
    assert get_fleet_status(db) == []


def test_fleet_status_reports_no_forecast_without_crashing(client, db):
    # A product with no trained model must not blow up the whole fleet
    # query — forced via a direct mock rather than relying on no
    # models/prophet_{id}.pkl existing on disk, since dev/CI environments
    # may have real trained models left over from prior runs that collide
    # with sequentially-assigned product IDs.
    product = create_product(client, name="Untrained Widget")
    purchase(client, product["id"], 12)

    with patch(
        "app.services.restock_service.forecast",
        side_effect=FileNotFoundError("no trained model"),
    ):
        statuses = get_fleet_status(db)

    assert len(statuses) == 1
    status = statuses[0]
    assert status["product_id"] == product["id"]
    assert status["name"] == "Untrained Widget"
    assert status["sku"] == product["sku"]
    assert status["current_inventory"] == 12
    assert status["urgency"] == "NO_FORECAST"
    assert status["recommended_order_qty"] is None


def test_fleet_status_includes_forecasted_product(client, db):
    create_product(client, name="Forecasted Widget")

    mock_forecast_df = pd.DataFrame(
        {
            "ds": pd.date_range("2026-04-01", periods=7),
            "yhat": [15.0] * 7,
            "yhat_lower": [10.0] * 7,
            "yhat_upper": [20.0] * 7,
        }
    )

    with patch("app.services.restock_service.forecast", return_value=mock_forecast_df):
        statuses = get_fleet_status(db)

    assert len(statuses) == 1
    status = statuses[0]
    assert status["urgency"] == "STOCKOUT"  # current inventory is 0
    assert status["projected_demand_7d"] == 105.0


def test_fleet_status_covers_every_product_alphabetically(client, db):
    create_product(client, name="Zebra")
    create_product(client, name="Apple")

    with patch(
        "app.services.restock_service.forecast",
        side_effect=FileNotFoundError("no trained model"),
    ):
        statuses = get_fleet_status(db)

    assert [s["name"] for s in statuses] == ["Apple", "Zebra"]
