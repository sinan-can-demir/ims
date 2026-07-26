# app/api/suppliers.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.supplier import SupplierCreate, SupplierResponse
from app.services.supplier_service import create_supplier, list_suppliers

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.post("", response_model=SupplierResponse, status_code=201)
def create_supplier_route(supplier: SupplierCreate, db: Session = Depends(get_db)):
    return create_supplier(db, supplier)


@router.get("", response_model=list[SupplierResponse])
def list_suppliers_route(db: Session = Depends(get_db)):
    return list_suppliers(db)
