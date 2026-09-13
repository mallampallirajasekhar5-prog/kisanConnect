from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
import schemas

# Standard baseline benchmark prices (in INR per kg/unit) for common agricultural commodities
CROP_BASELINES = {
    "tomato": 25.0,
    "tomatoes": 25.0,
    "mango": 120.0,
    "alphonso mango": 140.0,
    "rice": 45.0,
    "paddy": 30.0,
    "wheat": 28.0,
    "potato": 22.0,
    "potatoes": 22.0,
    "onion": 35.0,
    "onions": 35.0,
    "chilli": 90.0,
    "chilli pepper": 90.0,
    "banana": 35.0,
    "cotton": 75.0,
    "sugarcane": 15.0
}

CATEGORY_BASELINES = {
    "vegetables": 30.0,
    "fruits": 80.0,
    "grains": 40.0,
    "pulses": 95.0,
    "spices": 110.0,
    "commercial": 60.0
}


def suggest_crop_price(
    request: schemas.PriceSuggestRequest,
    db: Optional[Session] = None
) -> schemas.PriceSuggestResponse:
    """
    AI PRICE SUGGESTION ALGORITHM
    Suggests optimal selling price per unit by combining commodity baselines,
    real-time DB market supply, and demand pressure analysis.
    """
    crop_key = request.crop_name.strip().lower()
    cat_key = request.category.strip().lower()

    # 1. Determine baseline reference price
    base_price = CROP_BASELINES.get(crop_key)
    if not base_price:
        base_price = CATEGORY_BASELINES.get(cat_key, 35.0)

    # If current_price is provided by user, factor it in
    if request.current_price and request.current_price > 0:
        base_price = (base_price + request.current_price) / 2.0

    total_market_supply = 0.0
    db_avg_price = None

    # 2. Query real-time SQLite database statistics if session is provided
    if db:
        query = db.query(models.Product).filter(
            (models.Product.name.ilike(f"%{request.crop_name}%")) |
            (models.Product.category.ilike(f"%{request.category}%"))
        )

        products = query.all()
        if products:
            prices = [p.price for p in products if p.price > 0]
            quantities = [p.quantity for p in products if p.quantity > 0]

            if prices:
                db_avg_price = sum(prices) / len(prices)
            if quantities:
                total_market_supply = sum(quantities)

    # Blended price calculation
    if db_avg_price:
        blended_price = (base_price * 0.4) + (db_avg_price * 0.6)
    else:
        blended_price = base_price

    # 3. Supply/Demand adjustment
    # If supply is scarce (< 300 kg), apply scarcity premium
    # If supply is high (> 2000 kg), apply surplus adjustment
    if total_market_supply < 300:
        market_trend = "HIGH_DEMAND_PREMIUM"
        adjustment_factor = 1.12  # +12% premium
        reasoning = f"High demand and low market supply ({total_market_supply:.0f} {request.unit} listed). Recommended 12% premium."
    elif total_market_supply > 2000:
        market_trend = "SURPLUS_DISCOUNT"
        adjustment_factor = 0.92  # -8% competitive pricing
        reasoning = f"High market supply ({total_market_supply:.0f} {request.unit} listed). Slightly reduced price recommended for faster sales."
    else:
        market_trend = "FAIR_MARKET_PRICE"
        adjustment_factor = 1.02  # +2% optimal fair price
        reasoning = f"Balanced market supply ({total_market_supply:.0f} {request.unit} listed). Optimal direct-to-consumer price recommended."

    suggested_price = round(blended_price * adjustment_factor, 2)
    min_price = round(suggested_price * 0.88, 2)
    max_price = round(suggested_price * 1.15, 2)

    # Estimate potential profit margin for direct farmer sale (eliminating 25-30% middleman fees)
    potential_margin_pct = round(((suggested_price - (suggested_price * 0.65)) / suggested_price) * 100, 1)

    return schemas.PriceSuggestResponse(
        crop_name=request.crop_name,
        category=request.category,
        suggested_price=suggested_price,
        min_price=min_price,
        max_price=max_price,
        market_trend=market_trend,
        potential_margin_pct=potential_margin_pct,
        reasoning=reasoning
    )
