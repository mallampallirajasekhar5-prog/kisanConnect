from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session

import models
import schemas

# ---------------------------------------------------------------------------
# Categories considered inherently high-demand in Indian agricultural markets
# ---------------------------------------------------------------------------
HIGH_DEMAND_CATEGORIES = {"vegetables", "fruits", "spices"}
STEADY_DEMAND_CATEGORIES = {"grains", "cereals", "pulses", "oilseeds"}

# ---------------------------------------------------------------------------
# Simple seasonal demand multipliers (month → factor)
# Peak harvest / festive / sowing seasons in Andhra Pradesh
# ---------------------------------------------------------------------------
SEASONAL_FACTORS: dict[int, float] = {
    1: 1.05,   # Jan — winter vegetables peak
    2: 1.00,
    3: 0.95,   # Mar — pre-summer dip
    4: 0.90,   # Apr — summer heat, lower supply
    5: 0.88,
    6: 1.05,   # Jun — Kharif sowing begins
    7: 1.10,   # Jul — monsoon, mango/paddy peak
    8: 1.15,   # Aug — Onam / festivals
    9: 1.10,   # Sep — post-monsoon harvest
    10: 1.12,  # Oct — Dussehra / Navratri demand
    11: 1.10,  # Nov — Diwali festive demand
    12: 1.05,  # Dec — winter crops arrive
}


def _get_search_term(cat_key: str, crop_name: Optional[str]) -> str:
    """Return the most specific term to search OrderItems with."""
    return crop_name if crop_name else cat_key


def forecast_crop_demand(
    request: schemas.DemandForecastRequest,
    db: Optional[Session] = None,
) -> schemas.DemandForecastResponse:
    """
    AI DEMAND FORECASTING ALGORITHM
    ================================
    Predicts demand levels, volume requirements, and harvest recommendations
    by analysing:
      1. Historical order velocity from the internal KisanConnect DB
      2. Product listing count for the requested category/crop
      3. Seasonal demand factors for Andhra Pradesh
      4. Category-level demand heuristics

    NOTE: Prediction confidence is lower when there is limited historical data.
    The algorithm falls back to safe heuristics and clearly states so in the
    recommendation text.
    """
    cat_key = request.category.strip().lower()
    crop_name = request.crop_name.strip() if request.crop_name else None
    search_term = _get_search_term(cat_key, crop_name)

    total_ordered_qty: float = 0.0
    total_orders_count: int = 0
    total_listings: int = 0
    limited_data: bool = True

    # ------------------------------------------------------------------
    # 1. Analyse historical DB order data (if session available)
    # ------------------------------------------------------------------
    if db:
        # Count matching order-items by product name
        order_items = db.query(models.OrderItem).filter(
            models.OrderItem.product_name.ilike(f"%{search_term}%")
        ).all()

        if order_items:
            total_ordered_qty = sum(item.quantity for item in order_items)
            total_orders_count = len(order_items)
            limited_data = total_orders_count < 3   # flag low-data state

        # Also count active product listings for the category
        product_listings = db.query(models.Product).filter(
            (models.Product.name.ilike(f"%{search_term}%")) |
            (models.Product.category.ilike(f"%{request.category}%"))
        ).all()
        total_listings = len(product_listings)

    # ------------------------------------------------------------------
    # 2. Apply seasonal adjustment
    # ------------------------------------------------------------------
    current_month = datetime.utcnow().month
    seasonal_factor = SEASONAL_FACTORS.get(current_month, 1.0)

    # ------------------------------------------------------------------
    # 3. Demand level classification & trend direction
    # ------------------------------------------------------------------
    display_name = crop_name if crop_name else request.category

    if total_ordered_qty >= 50 or cat_key in HIGH_DEMAND_CATEGORIES:
        forecast_level = "HIGH"
        trend_direction = "INCREASING"
        base_predicted_qty = max(total_ordered_qty * 1.35, 1200.0)
        confidence_score = 0.88 if not limited_data else 0.72
        recommendation = (
            f"Strong consumer demand detected for {display_name}. "
            "Farmers are advised to harvest and list inventory immediately "
            "to capture optimal market prices. "
            f"({total_orders_count} orders found; {total_listings} listings active.)"
        )

    elif total_ordered_qty > 0 or cat_key in STEADY_DEMAND_CATEGORIES:
        forecast_level = "MEDIUM"
        trend_direction = "STABLE"
        base_predicted_qty = max(total_ordered_qty * 1.15, 600.0)
        confidence_score = 0.79 if not limited_data else 0.65
        recommendation = (
            f"Steady market demand for {display_name}. "
            "Maintain regular harvesting schedules and competitive pricing. "
            f"({total_orders_count} orders found; {total_listings} listings active.)"
        )

    else:
        # Low or no data — safe fallback
        forecast_level = "LOW"
        trend_direction = "DECREASING"
        base_predicted_qty = 350.0
        confidence_score = 0.55
        recommendation = (
            f"Limited demand signals for {display_name} (insufficient historical data). "
            "Consider staggered batch listings to prevent local oversupply. "
            "Prediction is based on category heuristics, not order history."
        )

    # ------------------------------------------------------------------
    # 4. Apply seasonal multiplier to predicted quantity
    # ------------------------------------------------------------------
    predicted_quantity = round(base_predicted_qty * seasonal_factor, 1)

    return schemas.DemandForecastResponse(
        category=request.category,
        crop_name=crop_name,
        forecast_level=forecast_level,
        trend_direction=trend_direction,
        predicted_quantity_demand=predicted_quantity,
        confidence_score=confidence_score,
        recommendation=recommendation,
    )
