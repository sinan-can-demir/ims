# app/services/supplier_service.py

from sqlalchemy.orm import Session

from app.core.exceptions import SupplierNotFoundError
from app.core.logging import logger
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate


def create_supplier(db: Session, supplier: SupplierCreate, organization_id: int = 1) -> Supplier:
    new_supplier = Supplier(
        name=supplier.name, contact_email=supplier.contact_email, organization_id=organization_id
    )
    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)

    logger.info("supplier_created", extra={"supplier_id": new_supplier.id})

    return new_supplier


def get_supplier(db: Session, supplier_id: int, organization_id: int = 1) -> Supplier:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.organization_id == organization_id)
        .first()
    )
    if not supplier:
        raise SupplierNotFoundError(supplier_id)
    return supplier


def list_suppliers(db: Session, organization_id: int = 1) -> list[Supplier]:
    return (
        db.query(Supplier)
        .filter(Supplier.organization_id == organization_id)
        .order_by(Supplier.name.asc())
        .all()
    )
