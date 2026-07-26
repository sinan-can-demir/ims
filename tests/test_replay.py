from .utils import create_product


def test_rebuild_inventory_state(admin_client):
    # POST /api/inventory/replay is admin-gated; use admin_client throughout
    # since this test is about replay behavior, not the role check itself
    # (that's covered in tests/test_rbac.py).
    client = admin_client

    # Setup: Create product and generate some events
    product = create_product(client)
    product_id = product["id"]

    # create some events
    client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": "PURCHASE",
            "quantity": 50,
            "event_id": "replay-1",
        },
    )

    client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": "SALE",
            "quantity": 10,
            "event_id": "replay-2",
        },
    )

    # Verify initial inventory level
    response_before = client.get(f"/api/inventory/{product_id}")
    assert response_before.status_code == 200
    assert response_before.json()["quantity"] == 40

    # Call the replay endpoint to rebuild inventory state
    replay_response = client.post("/api/inventory/replay")
    assert replay_response.status_code == 200

    # Verify inventory level is still correct after replay
    response_after = client.get(f"/api/inventory/{product_id}")
    assert response_after.status_code == 200
    assert response_after.json()["quantity"] == 40

    # Verify the replay summary contains correct counts
    summary = replay_response.json()
    assert summary["events_processed"] == 2
    assert summary["products_rebuilt"] == 1
