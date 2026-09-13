from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

import database
import schemas
from ai.route_optimizer import optimize_delivery_route
from ai.price_suggestion import suggest_crop_price
from ai.demand_forecast import forecast_crop_demand

router = APIRouter(prefix="/ai", tags=["AI Intelligence Layer"])


@router.post("/route-optimize", response_model=schemas.RouteOptimizeResponse)
def route_optimization_api(
    request: schemas.RouteOptimizeRequest,
    db: Session = Depends(database.get_db)
):
    """
    AI ROUTE OPTIMIZATION API
    Calculates driving distance using Haversine algorithm, travel time, step-by-step directions,
    and updates DB delivery record if delivery_id is supplied.
    """
    return optimize_delivery_route(request=request, db=db)


@router.post("/price-suggest", response_model=schemas.PriceSuggestResponse)
def price_suggestion_api(
    request: schemas.PriceSuggestRequest,
    db: Session = Depends(database.get_db)
):
    """
    AI PRICE SUGGESTION API
    Suggests optimal selling price per unit using commodity baselines, live market supply, and demand pressure.
    """
    return suggest_crop_price(request=request, db=db)


@router.post("/demand-forecast", response_model=schemas.DemandForecastResponse)
def demand_forecasting_api(
    request: schemas.DemandForecastRequest,
    db: Session = Depends(database.get_db)
):
    """
    AI DEMAND FORECASTING API
    Predicts market demand level (HIGH, MEDIUM, LOW), trend direction, sales volume, and farmer harvest advisory.
    """
    return forecast_crop_demand(request=request, db=db)
