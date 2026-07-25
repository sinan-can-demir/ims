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
