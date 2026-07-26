# app/core/exceptions.py
#
# Domain-level exceptions raised by the service layer. Framework-agnostic on
# purpose — services shouldn't import FastAPI. app/main.py registers a single
# exception handler keyed on DomainError that reads status_code off whichever
# subclass was raised, so routers don't need their own try/except for these.


class DomainError(Exception):
    status_code = 500


class ProductNotFoundError(DomainError):
    status_code = 404

    def __init__(self, product_id: int):
        self.product_id = product_id
        super().__init__(f"Product {product_id} not found")


class DuplicateSKUError(DomainError):
    status_code = 409

    def __init__(self, sku: str):
        self.sku = sku
        super().__init__(f"Product with this SKU already exists: {sku}")


class ProductSkuNotFoundError(DomainError):
    status_code = 404

    def __init__(self, sku: str):
        self.sku = sku
        super().__init__(f"Product with SKU '{sku}' not found")


class InvalidEventError(DomainError):
    status_code = 400


class InvalidCredentialsError(DomainError):
    status_code = 401

    def __init__(self):
        super().__init__("Invalid email or password")


class InsufficientInventoryError(DomainError):
    status_code = 400

    def __init__(self, product_id: int, current_quantity: int, requested_delta: int):
        self.product_id = product_id
        self.current_quantity = current_quantity
        self.requested_delta = requested_delta
        super().__init__("Insufficient inventory")


class SupplierNotFoundError(DomainError):
    status_code = 404

    def __init__(self, supplier_id: int):
        self.supplier_id = supplier_id
        super().__init__(f"Supplier {supplier_id} not found")


class PurchaseOrderNotFoundError(DomainError):
    status_code = 404

    def __init__(self, purchase_order_id: int):
        self.purchase_order_id = purchase_order_id
        super().__init__(f"Purchase order {purchase_order_id} not found")


class PurchaseOrderLineNotFoundError(DomainError):
    status_code = 404

    def __init__(self, line_id: int):
        self.line_id = line_id
        super().__init__(f"Purchase order line {line_id} not found")


class InvalidPurchaseOrderStateError(DomainError):
    status_code = 400

    def __init__(self, purchase_order_id: int, current_status: str, attempted_action: str):
        self.purchase_order_id = purchase_order_id
        self.current_status = current_status
        self.attempted_action = attempted_action
        super().__init__(
            f"Cannot {attempted_action} purchase order {purchase_order_id} "
            f"in status {current_status}"
        )


class RestockNotNeededError(DomainError):
    status_code = 400

    def __init__(self, product_id: int, recommended_order_qty: int):
        self.product_id = product_id
        self.recommended_order_qty = recommended_order_qty
        super().__init__(
            f"Product {product_id}'s recommended order quantity is "
            f"{recommended_order_qty} — no PO needed right now"
        )
