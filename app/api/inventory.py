import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.database import get_db
from app.models.inventory_event import InventoryEvent
from app.models.user import User
from app.schemas.export import ExportMetadata
from app.schemas.ingestion import IngestResponse
from app.schemas.inventory_event import InventoryEventCreate, InventoryEventResponse
from app.schemas.inventory_state import InventoryStateResponse
from app.services.export_service import export_inventory_events
from app.services.ingestion_service import ingest_events
from app.services.inventory_service import get_inventory, record_event
from app.services.replay_service import rebuild_inventory_state

router = APIRouter(prefix="/inventory", tags=["inventory"])

_BULK_IMPORT_COLUMNS = ["sku", "event_type", "quantity", "event_id"]


@router.post("/events", response_model=InventoryEventResponse, status_code=201)
def create_inventory_event(
    event: InventoryEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    return record_event(
        db, event.product_id, event.event_type, event.quantity, event.event_id, current_user.id
    )


@router.post("/events/bulk", response_model=IngestResponse)
def bulk_import_events(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    """
    Generic CSV bulk import for inventory events. Columns:
    sku, event_type, quantity, event_id. Partial success is expected —
    each row is resolved and recorded independently, see IngestResponse.
    """
    try:
        df = pd.read_csv(file.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    missing = [col for col in _BULK_IMPORT_COLUMNS if col not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing required columns: {', '.join(missing)}",
        )

    rows = df[_BULK_IMPORT_COLUMNS].to_dict(orient="records")
    return ingest_events(db, rows, current_user.id)


@router.post("/replay")
def replay_inventory_projection(db: Session = Depends(get_db)):
    return rebuild_inventory_state(db)


@router.get("/events/{product_id}", response_model=list[InventoryEventResponse])
def get_product_events(
    product_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    events = (
        db.query(InventoryEvent)
        .filter(InventoryEvent.product_id == product_id)
        .order_by(InventoryEvent.created_at.asc(), InventoryEvent.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return events


@router.get("/{product_id}", response_model=InventoryStateResponse)
def inventory_level(product_id: int, db: Session = Depends(get_db)):
    return InventoryStateResponse(product_id=product_id, quantity=get_inventory(db, product_id))


@router.post("/export", response_model=ExportMetadata)
def export_inventory(db: Session = Depends(get_db)):
    return export_inventory_events(db, incremental=True)
