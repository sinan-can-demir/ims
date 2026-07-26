# app/services/supplier_service.py

from sqlalchemy.orm import Session

from app.core.exceptions import SupplierNotFoundError
from app.core.logging import logger
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate


def create_supplier(db: Session, supplier: SupplierCreate) -> Supplier:
    new_supplier = Supplier(name=supplier.name, contact_email=supplier.contact_email)
    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)

    logger.info("supplier_created", extra={"supplier_id": new_supplier.id})

    return new_supplier


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise SupplierNotFoundError(supplier_id)
    return supplier


def list_suppliers(db: Session) -> list[Supplier]:
    return db.query(Supplier).order_by(Supplier.name.asc()).all()
