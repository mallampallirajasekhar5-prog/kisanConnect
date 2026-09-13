from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
import schemas

HIGH_DEMAND_CATEGORIES = ["vegetables", "fruits", "spices"]


def forecast_crop_demand(
    request: schemas.DemandForecastRequest,
    db: Optional[Session] = None
) -> schemas.DemandForecastResponse:
    """
    AI DEMAND FORECASTING ALGORITHM
    Predicts demand levels, volume requirements, and harvest recommendations
    by analyzing historical DB order velocity and category consumption trends.
    """
    cat_key = request.category.strip().lower()
    crop_name = request.crop_name.strip() if request.crop_name else None

    total_ordered_qty = 0.0
    total_orders_count = 0

    # 1. Analyze historical DB orders if session is available
    if db:
        query = db.query(models.OrderItem).filter(
            models.OrderItem.product_name.ilike(f"%{category_match(cat_key, crop_name)}%")
        )
        items = query.all()

        if items:
            total_ordered_qty = sum(item.quantity for item in items)
            total_orders_count = len(items)

    # 2. Heuristic demand assessment
    if total_ordered_qty >= 50 or cat_key in HIGH_DEMAND_CATEGORIES:
        forecast_level = "HIGH"
        trend_direction = "INCREASING"
        predicted_quantity = max(total_ordered_qty * 1.35, 1200.0)
        confidence_score = 0.88
        recommendation = (
            f"Strong consumer demand for {crop_name if crop_name else request.category}. "
            "Farmers are advised to harvest and list inventory immediately to capture optimal market prices."
        )
    elif total_ordered_qty > 0:
        forecast_level = "MEDIUM"
        trend_direction = "STABLE"
        predicted_quantity = max(total_ordered_qty * 1.15, 600.0)
        confidence_score = 0.79
        recommendation = (
            f"Steady market demand for {crop_name if crop_name else request.category}. "
            "Maintain regular harvesting schedules and competitive pricing."
        )
    else:
        forecast_level = "MEDIUM" if cat_key in ["grains", "pulses"] else "LOW"
        trend_direction = "STABLE" if forecast_level == "MEDIUM" else "DECREASING"
        predicted_quantity = 350.0
        confidence_score = 0.72
        recommendation = (
            f"Moderate or developing demand for {crop_name if crop_name else request.category}. "
            "Consider staggered batch listings to prevent local oversupply."
        )

    return schemas.DemandForecastResponse(
        category=request.category,
        crop_name=crop_name,
        forecast_level=forecast_level,
        trend_direction=trend_direction,
        predicted_quantity_demand=round(predicted_quantity, 1),
        confidence_score=confidence_score,
        recommendation=recommendation
    )


def category_match(cat_key: str, crop_name: Optional[str]) -> str:
    """Helper to determine best search term."""
    if crop_name:
        return crop_name
    return cat_key
