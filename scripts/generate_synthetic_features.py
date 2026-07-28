# scripts/generate_synthetic_features.py
#
# Generates synthetic daily_sales feature data directly into the feature store.
# This is a bootstrapping tool for development and model training when real
# historical data is not yet available.
#
# In production, this file would not exist — the feature store would be
# populated by the real pipeline: make export → make dbt-run → make features
#
# Usage:
#   python scripts/generate_synthetic_features.py

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.config import FEATURE_STORE_PATH
from app.core import storage

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

START_DATE = date(2026, 3, 1)
DAYS = 30

# One profile per product — mirrors the seed_data.py demand profiles
# mean = average daily units sold, std = noise level
PRODUCTS = [
    {
        "product_id": 8,
        "name": "Widget A",
        "mean_demand": 15,
        "std": 4,
        "trend": 0.2,  # slight upward trend over 30 days
    },
    {
        "product_id": 9,
        "name": "Widget B",
        "mean_demand": 5,
        "std": 2,
        "trend": 0.0,  # flat demand
    },
    {
        "product_id": 10,
        "name": "Widget C",
        "mean_demand": 30,
        "std": 8,
        "trend": -0.3,  # slight downward trend
    },
]

# -------------------------------------------------------------------
# Weekly seasonality pattern
# Multipliers per day of week: Mon=0, Tue=1, ..., Sun=6
# Real inventory systems often see lower sales on weekends
# -------------------------------------------------------------------
WEEKLY_PATTERN = {
    0: 1.2,  # Monday    — high
    1: 1.1,  # Tuesday
    2: 1.0,  # Wednesday — baseline
    3: 1.0,  # Thursday
    4: 1.3,  # Friday    — highest
    5: 0.6,  # Saturday  — low
    6: 0.5,  # Sunday    — lowest
}


def generate_product_features(product: dict, dates: list[date]) -> pd.DataFrame:
    """
    Generate daily feature rows for a single product.
    Includes trend, weekly seasonality, and random noise.
    """
    np.random.seed(product["product_id"])  # reproducible per product

    rows = []
    for i, d in enumerate(dates):
        # Trend component — linear drift over time
        trend_component = product["trend"] * i

        # Seasonality component — day of week multiplier
        seasonality = WEEKLY_PATTERN[d.weekday()]

        # Base demand with trend and noise
        base = (product["mean_demand"] + trend_component) * seasonality
        noise = np.random.normal(0, product["std"])
        units_sold = max(0, round(base + noise))

        # Purchases happen roughly every 10 days
        units_purchased = 0
        if i % 10 == 0:
            units_purchased = product["mean_demand"] * 12

        # Occasional returns — roughly 1 in 7 days
        returns = 0
        if np.random.random() < 0.14:
            returns = np.random.randint(1, 4)

        net_delta = units_purchased + returns - units_sold

        rows.append(
            {
                "product_id": product["product_id"],
                "date": d.isoformat(),
                "units_sold": float(units_sold),
                "units_purchased": float(units_purchased + returns),
                "net_delta": float(net_delta),
            }
        )

    df = pd.DataFrame(rows)

    # Rolling 7-day average of units_sold — same logic as feature_service.py
    df["rolling_avg_7d"] = df["units_sold"].rolling(7, min_periods=1).mean().round(2)

    return df


def main() -> None:
    print("=" * 55)
    print("IMS Synthetic Feature Generator")
    print("=" * 55)

    dates = [START_DATE + timedelta(days=i) for i in range(DAYS)]

    frames = []
    for product in PRODUCTS:
        df = generate_product_features(product, dates)
        frames.append(df)
        print(f"  ✓ {product['name']} (id={product['product_id']}) — {len(df)} rows generated")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["product_id", "date"]).reset_index(drop=True)

    # Write to feature store
    storage.mkdir(FEATURE_STORE_PATH)
    output_path = storage.join(FEATURE_STORE_PATH, "daily_sales.parquet")
    storage.to_parquet(combined, output_path)

    print(f"\n✓ Written to {output_path}")
    print(f"  Total rows : {len(combined)}")
    print(f"  Date range : {dates[0]} → {dates[-1]}")
    print(f"  Products   : {combined['product_id'].nunique()}")
    print()
    print("Sample:")
    print(combined.head(10).to_string(index=False))
    print()
    print("Next step:")
    print("  make train")
    print("=" * 55)


if __name__ == "__main__":
    main()
