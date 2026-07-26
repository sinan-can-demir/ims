# tests/test_edge_cases.py

import uuid

from .utils import create_product


def _event(client, product_id, event_type, quantity, event_id=None):
    event_id = event_id or f"evt-{uuid.uuid4()}"
    response = client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": event_type,
            "quantity": quantity,
            "event_id": event_id,
        },
    )
    return response


def _quantity(client, product_id):
    return client.get(f"/api/inventory/{product_id}").json()["quantity"]


# ---------------------------------------------------------------------------
# Return → Damage sequence
# ---------------------------------------------------------------------------


def test_return_then_damage_sequence(client):
    """
    Verifies that RETURN increases inventory and DAMAGE decreases it correctly
    in sequence. Tests the full event type coverage beyond PURCHASE/SALE.
    """
    product = create_product(client)
    pid = product["id"]

    # Start with a base stock
    _event(client, pid, "PURCHASE", 20)
    assert _quantity(client, pid) == 20

    # Customer returns 10 units
    _event(client, pid, "RETURN", 10)
    assert _quantity(client, pid) == 30

    # 5 units found damaged
    _event(client, pid, "DAMAGE", 5)
    assert _quantity(client, pid) == 25


def test_return_requires_positive_quantity(client):
    """
    RETURN with negative quantity must be rejected — same rule as PURCHASE.
    """
    product = create_product(client)
    pid = product["id"]

    response = _event(client, pid, "RETURN", -10)
    assert response.status_code == 400


def test_damage_requires_positive_quantity(client):
    """
    DAMAGE with negative quantity must be rejected — same rule as SALE.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 50)
    response = _event(client, pid, "DAMAGE", -5)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# WASTE — spoilage/waste, tracked distinctly from DAMAGE
# ---------------------------------------------------------------------------


def test_waste_decreases_inventory(client):
    """
    WASTE behaves like DAMAGE for stock purposes (decreases quantity,
    oversell-protected) but is tracked as its own event type.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 20)
    response = _event(client, pid, "WASTE", 5)
    assert response.status_code == 201
    assert response.json()["event_type"] == "WASTE"
    assert _quantity(client, pid) == 15


def test_waste_requires_positive_quantity(client):
    """
    WASTE with negative quantity must be rejected — same rule as SALE/DAMAGE.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 50)
    response = _event(client, pid, "WASTE", -5)
    assert response.status_code == 400


def test_waste_blocked_by_oversell_protection(client):
    """
    WASTE cannot drive stock negative — same oversell guard as SALE/DAMAGE.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 5)
    response = _event(client, pid, "WASTE", 10)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Large adjustment edge cases
# ---------------------------------------------------------------------------


def test_adjustment_large_positive(client):
    """
    Large positive ADJUSTMENT must succeed.
    ADJUSTMENT bypasses oversell protection by design — it is a manual
    correction tool, not a transactional event.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 100)
    _event(client, pid, "ADJUSTMENT", 999)
    assert _quantity(client, pid) == 1099


def test_adjustment_drives_stock_negative(client):
    """
    ADJUSTMENT is intentionally allowed to drive stock negative.
    This represents a physical count correction — the system trusts
    the operator to reconcile discrepancies, including cases where
    the real stock is lower than the system shows.

    This is a conscious design decision, not a missing guard.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 50)
    response = _event(client, pid, "ADJUSTMENT", -200)

    assert response.status_code == 201
    assert _quantity(client, pid) == -150


def test_adjustment_zero_rejected(client):
    """
    Zero quantity is rejected for all event types including ADJUSTMENT.
    A zero adjustment has no meaning and likely indicates a client error.
    """
    product = create_product(client)
    pid = product["id"]

    response = _event(client, pid, "ADJUSTMENT", 0)
    assert response.status_code == 422  # Pydantic rejects zero at schema level


def test_adjustment_back_to_positive(client):
    """
    After a large negative adjustment, a positive adjustment
    must correctly restore stock to the expected level.
    """
    product = create_product(client)
    pid = product["id"]

    _event(client, pid, "PURCHASE", 50)
    _event(client, pid, "ADJUSTMENT", -200)
    assert _quantity(client, pid) == -150

    _event(client, pid, "ADJUSTMENT", 200)
    assert _quantity(client, pid) == 50
