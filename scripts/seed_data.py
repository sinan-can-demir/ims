# scripts/seed_data.py
#
# Generates realistic inventory events spread across 30 days for 3 products.
#
# Writes directly to the database instead of going through the HTTP API.
# InventoryEvent.created_at is server-stamped (app/models/inventory_event.py)
# by design — events are the source of truth and clients can't backdate them
# — but that means there's no way to get 30 distinct calendar days of history
# out of the API in one sitting; every event would land on today's date.
# Setting created_at directly here is the one place that's the point, not a
# workaround: this script is generating demo history, not simulating a
# client. Reuses normalize_quantity (app/services/inventory_service.py) for
# quantity sign handling and rebuild_inventory_state
# (app/services/replay_service.py) to derive the final projection, so the
# resulting DB state is exactly what real event replay would produce.
#
# Usage:
#   python scripts/seed_data.py
#
# Requirements:
#   - Postgres must be reachable at DATABASE_URL (make up)

import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models.enums import EventType  # noqa: E402
from app.models.inventory_event import InventoryEvent  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.services.inventory_service import normalize_quantity  # noqa: E402
from app.services.replay_service import rebuild_inventory_state  # noqa: E402

# -------------------------------------------------------------------
# Products to seed
# -------------------------------------------------------------------
PRODUCTS = [
    {"name": "Widget A", "sku": "WGT-001"},
    {"name": "Widget B", "sku": "WGT-002"},
    {"name": "Widget C", "sku": "WGT-003"},
]

# -------------------------------------------------------------------
# Demand profiles — units sold per day follow these patterns
# Each tuple is (mean_daily_sales, std_dev)
# std_dev adds realistic noise so the model has something to learn
# -------------------------------------------------------------------
DEMAND_PROFILES = {
    "WGT-001": {"mean": 15, "std": 4},  # steady seller
    "WGT-002": {"mean": 5, "std": 2},  # slow mover
    "WGT-003": {"mean": 30, "std": 8},  # high volume
}

START_DATE = date(2026, 3, 1)
DAYS = 30


def _event_time(day: date) -> datetime:
    # Midday UTC keeps every event unambiguously on its intended calendar
    # day, regardless of the reader's timezone.
    return datetime(day.year, day.month, day.day, 12, 0, 0, tzinfo=timezone.utc)


def create_products(db) -> dict[str, int]:
    """Create products and return a mapping of SKU -> product_id."""
    product_ids = {}

    for product in PRODUCTS:
        existing = db.query(Product).filter(Product.sku == product["sku"]).first()

        if existing:
            # Already exists — this is fine, seed is idempotent.
            print(
                f"  ⚠ {product['name']} already exists (SKU conflict). "
                f"Run make reset first for a clean seed."
            )
            product_ids[product["sku"]] = existing.id
            continue

        row = Product(name=product["name"], sku=product["sku"])
        db.add(row)
        db.flush()
        product_ids[product["sku"]] = row.id
        print(f"  ✓ Created {product['name']} (id={row.id})")

    db.commit()
    return product_ids


def _record(
    db,
    product_id: int,
    event_type: EventType,
    quantity: int,
    event_id: str,
    when: datetime,
) -> bool:
    """Insert one backdated event. Returns False (no-op) if event_id already exists."""
    existing = db.query(InventoryEvent).filter(InventoryEvent.event_id == event_id).first()
    if existing:
        return False

    delta = normalize_quantity(event_type, quantity)
    db.add(
        InventoryEvent(
            product_id=product_id,
            event_type=event_type,
            quantity=delta,
            event_id=event_id,
            created_at=when,
            # No human actor for synthetic seed data — same as webhook-sourced
            # events, NULL is honest here.
            created_by_id=None,
        )
    )
    return True


def seed_events(db, product_ids: dict[str, int]) -> None:
    """
    For each product, generate 30 days of realistic events:
    - Initial PURCHASE on day 1 (bulk restock)
    - Daily SALE events with realistic demand noise
    - Occasional RETURN events (roughly 1 in 7 days)
    - Mid-period PURCHASE restock when stock gets low
    """
    for sku, product_id in product_ids.items():
        profile = DEMAND_PROFILES[sku]
        mean = profile["mean"]
        std = profile["std"]
        stock = 0  # running total, mirrors the app's oversell protection

        print(f"\n  Seeding {sku} (product_id={product_id})...")

        # --- Initial bulk purchase on day 1 ---
        initial_stock = mean * 20  # ~20 days of stock to start
        if _record(
            db,
            product_id,
            EventType.PURCHASE,
            initial_stock,
            f"seed-purchase-initial-{sku}",
            _event_time(START_DATE),
        ):
            stock += initial_stock
        print(f"    Day 0: PURCHASE {initial_stock} units (initial stock)")

        for day_offset in range(DAYS):
            current_date = START_DATE + timedelta(days=day_offset)
            when = _event_time(current_date)
            day_label = current_date.isoformat()

            # --- Daily sale ---
            # clip at 1 to avoid zero or negative quantities
            daily_demand = max(1, int(random.gauss(mean, std)))

            if stock - daily_demand < 0:
                # Oversell protection would trigger — restock before continuing,
                # same as the app returning 400 and the original seed script
                # reacting to it.
                restock_qty = mean * 10
                if _record(
                    db,
                    product_id,
                    EventType.PURCHASE,
                    restock_qty,
                    f"seed-restock-{sku}-{day_label}",
                    when,
                ):
                    stock += restock_qty
                print(f"    {day_label}: ⚠ Oversell avoided → PURCHASE {restock_qty} (emergency)")
            else:
                if _record(
                    db,
                    product_id,
                    EventType.SALE,
                    daily_demand,
                    f"seed-sale-{sku}-{day_label}",
                    when,
                ):
                    stock -= daily_demand
                print(f"    {day_label}: SALE {daily_demand} units")

            # --- Occasional return (roughly 1 in 7 days) ---
            if random.random() < 0.14:  # noqa: S311 -- synthetic demo data, not security-sensitive
                return_qty = random.randint(1, 3)  # noqa: S311
                if _record(
                    db,
                    product_id,
                    EventType.RETURN,
                    return_qty,
                    f"seed-return-{sku}-{day_label}",
                    when,
                ):
                    stock += return_qty
                print(f"    {day_label}: RETURN {return_qty} units")

            # --- Mid-period restock (around day 15) ---
            if day_offset == 14:
                restock_qty = mean * 15
                if _record(
                    db, product_id, EventType.PURCHASE, restock_qty, f"seed-restock-mid-{sku}", when
                ):
                    stock += restock_qty
                print(f"    {day_label}: PURCHASE {restock_qty} units (mid-period restock)")

        db.commit()


def main() -> None:
    print("=" * 55)
    print("IMS Seed Script — 30 days of realistic inventory data")
    print("=" * 55)

    db = SessionLocal()
    try:
        # 1. Create products
        print("\n[1/2] Creating products...")
        product_ids = create_products(db)

        if not product_ids:
            print("\n✗ No products created. Exiting.")
            return

        # 2. Seed events
        print("\n[2/2] Seeding inventory events...")
        seed_events(db, product_ids)

        # 3. Rebuild the inventory_state projection from the events just written
        summary = rebuild_inventory_state(db)

        # 4. Summary
        print("\n" + "=" * 55)
        print("✓ Seeding complete.")
        print(f"  Products seeded : {len(product_ids)}")
        print(f"  Days of history : {DAYS}")
        print(f"  Events replayed : {summary['events_processed']}")
        print()
        print("Next steps:")
        print("  make export")
        print("  make warehouse")
        print("  make dbt-run")
        print("  make dbt-test")
        print("  make features")
        print("  make train")
        print("=" * 55)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
