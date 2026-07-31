import hashlib
import hmac
import json
import uuid

from app.models.organization import Organization


def create_product(client, name="Item"):
    response = client.post("/api/products", json={"name": name, "sku": f"sku-{uuid.uuid4()}"})

    # Ensure product creation was successful
    # and status code is 201 (Created)
    assert response.status_code == 201, response.json()

    return response.json()


def purchase(client, product_id, quantity):
    event_id = f"evt-{uuid.uuid4()}"
    response = client.post(
        "/api/inventory/events",
        json={
            "product_id": product_id,
            "event_type": "PURCHASE",
            "quantity": quantity,
            "event_id": event_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_supplier(client, name="Acme Foods"):
    response = client.post("/api/suppliers", json={"name": name})
    assert response.status_code == 201, response.json()
    return response.json()


def create_draft_po(client, supplier_id, product_id, quantity=10):
    response = client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def recipe_item(client, finished_product_id, component_product_id, quantity):
    return client.post(
        "/api/recipes",
        json={
            "finished_product_id": finished_product_id,
            "component_product_id": component_product_id,
            "quantity": quantity,
        },
    )


def set_webhook_secret(db, organization_id, secret):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org.webhook_secret = secret
    db.commit()


def signed_webhook_request(client, organization_id, payload, secret):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        f"/api/webhooks/{organization_id}/ingest",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )
