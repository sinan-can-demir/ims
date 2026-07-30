# app/api/forecast.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_org_id
from app.core.exceptions import DomainError
from app.core.logging import logger
from app.database import get_db
from app.schemas.forecast import ForecastPoint, ForecastResponse, RestockResponse
from app.services.forecast_service import forecast
from app.services.restock_service import get_restock_recommendation

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{product_id}", response_model=ForecastResponse)
def get_forecast(product_id: int, days: int = Query(default=7, ge=1, le=90)):
    """
    Return a demand forecast for the next N days.
    Requires a trained model — run make train first.
    """
    try:
        df = forecast(product_id, days=days)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("forecast_failed", extra={"product_id": product_id})
        raise HTTPException(status_code=500, detail="Internal server error")

    predictions = [
        ForecastPoint(
            date=row["ds"].date(),
            predicted_units=max(0, round(row["yhat"], 2)),
            lower_bound=max(0, round(row["yhat_lower"], 2)),
            upper_bound=max(0, round(row["yhat_upper"], 2)),
        )
        for _, row in df.iterrows()
    ]

    return ForecastResponse(
        product_id=product_id,
        forecast_days=days,
        predictions=predictions,
    )


@router.get("/restock/{product_id}", response_model=RestockResponse)
def get_restock(
    product_id: int,
    db: Session = Depends(get_db),
    organization_id: int = Depends(get_current_org_id),
):
    """
    Return a recommended restock quantity
    """
    try:
        result = get_restock_recommendation(db, product_id, organization_id)
    except DomainError:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("restock_failed", extra={"product_id": product_id})
        raise HTTPException(status_code=500, detail="Internal server error")

    return result
