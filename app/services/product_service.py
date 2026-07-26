from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateSKUError, ProductSkuNotFoundError
from app.core.logging import logger
from app.models.product import Product
from app.schemas.product import ProductCreate


def create_product(db: Session, product: ProductCreate) -> Product:
    new_product = Product(name=product.name, sku=product.sku)

    try:
        db.add(new_product)
        db.commit()
        db.refresh(new_product)

        logger.info("product_created", extra={"product_id": new_product.id, "sku": product.sku})

        return new_product

    except IntegrityError:
        db.rollback()
        raise DuplicateSKUError(product.sku)


def get_product_by_sku(db: Session, sku: str) -> Product:
    product = db.query(Product).filter(Product.sku == sku).first()
    if not product:
        raise ProductSkuNotFoundError(sku)
    return product


def list_products(db: Session) -> list[Product]:
    return db.query(Product).order_by(Product.name.asc()).all()
