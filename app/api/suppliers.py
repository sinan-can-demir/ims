# app/api/suppliers.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_org_id
from app.database import get_db
from app.schemas.supplier import SupplierCreate, SupplierResponse
from app.services.supplier_service import create_supplier, list_suppliers

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.post("", response_model=SupplierResponse, status_code=201)
def create_supplier_route(
    supplier: SupplierCreate,
    db: Session = Depends(get_db),
    organization_id: int = Depends(get_current_org_id),
):
    return create_supplier(db, supplier, organization_id)


@router.get("", response_model=list[SupplierResponse])
def list_suppliers_route(
    db: Session = Depends(get_db), organization_id: int = Depends(get_current_org_id)
):
    return list_suppliers(db, organization_id)
