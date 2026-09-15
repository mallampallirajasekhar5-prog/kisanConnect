from typing import Optional
from sqlalchemy.orm import Session

import models
import schemas

# ---------------------------------------------------------------------------
# Standard baseline benchmark prices (INR per kg/unit)
# Reference: APMC average rates for Andhra Pradesh region
# NOTE: No live external market-data API is connected.
# Prices are estimates based on internal project data + curated benchmarks.
# ---------------------------------------------------------------------------
CROP_BASELINES: dict = {
    # Vegetables
    "tomato": 25.0, "tomatoes": 25.0,
    "potato": 22.0, "potatoes": 22.0,
    "onion": 35.0, "onions": 35.0,
    "brinjal": 20.0, "eggplant": 20.0,
    "cauliflower": 28.0, "cabbage": 18.0,
    "carrot": 30.0, "spinach": 22.0,
    "lady finger": 30.0, "okra": 30.0,
    "bitter gourd": 35.0, "cucumber": 20.0,
    # Fruits
    "mango": 120.0, "alphonso mango": 140.0,
    "banana": 35.0, "papaya": 25.0,
    "guava": 40.0, "orange": 60.0,
    "watermelon": 15.0, "grapes": 80.0,
    "pomegranate": 100.0,
    # Grains & Cereals
    "rice": 45.0, "paddy": 30.0,
    "wheat": 28.0, "maize": 22.0, "corn": 22.0,
    "jowar": 26.0, "bajra": 24.0, "ragi": 38.0,
    # Pulses
    "dal": 90.0, "lentils": 90.0,
    "chickpea": 85.0, "chana": 85.0,
    "moong dal": 95.0, "urad dal": 100.0, "toor dal": 110.0,
    # Spices / Cash crops
    "chilli": 90.0, "chilli pepper": 90.0,
    "turmeric": 130.0, "ginger": 80.0,
    "garlic": 75.0, "pepper": 350.0,
    "coriander": 60.0,
    # Commercial
    "cotton": 75.0, "sugarcane": 15.0,
    "groundnut": 55.0, "sunflower": 58.0, "soybean": 50.0,
}

CATEGORY_BASELINES: dict = {
    "vegetables": 28.0,
    "fruits": 75.0,
    "grains": 38.0,
    "cereals": 35.0,
    "pulses": 95.0,
    "spices": 120.0,
    "commercial": 60.0,
    "oilseeds": 55.0,
    "dairy": 50.0,
}


def suggest_crop_price(
    request: schemas.PriceSuggestRequest,
    db: Optional[Session] = None,
) -> schemas.PriceSuggestResponse:
    """
    AI PRICE SUGGESTION ALGORITHM
    ==============================
    Estimates optimal selling price per unit by combining:
      1. Commodity baseline benchmarks (APMC reference rates)
      2. Live DB market data — average listing prices & total supply from
         the KisanConnect product catalogue (when a DB session is provided)
      3. Supply/Demand adjustment factor

    NOTE: No external live market-data API is connected.
    Results are estimations derived from internal DB records and benchmarks.
    """
    crop_key = request.crop_name.strip().lower()
    cat_key = request.category.strip().lower()

    # ------------------------------------------------------------------
    # 1. Baseline reference price
    # ------------------------------------------------------------------
    base_price: float = CROP_BASELINES.get(crop_key) or CATEGORY_BASELINES.get(cat_key, 35.0)

    # Blend in caller-supplied current price if available
    if request.current_price and request.current_price > 0:
        base_price = (base_price * 0.5) + (request.current_price * 0.5)

    # ------------------------------------------------------------------
    # 2. Query internal DB for live market statistics
    # ------------------------------------------------------------------
    total_market_supply: float = 0.0
    db_avg_price: Optional[float] = None

    if db:
        matching_products = db.query(models.Product).filter(
            (models.Product.name.ilike(f"%{request.crop_name}%")) |
            (models.Product.category.ilike(f"%{request.category}%"))
        ).all()

        if matching_products:
            prices = [p.price for p in matching_products if p.price > 0]
            quantities = [p.quantity for p in matching_products if p.quantity > 0]
            if prices:
                db_avg_price = sum(prices) / len(prices)
            if quantities:
                total_market_supply = sum(quantities)

    # ------------------------------------------------------------------
    # 3. Blended price  (baseline 40% + DB average 60% when available)
    # ------------------------------------------------------------------
    if db_avg_price:
        blended_price = (base_price * 0.4) + (db_avg_price * 0.6)
        data_source = f"internal DB average \u20b9{db_avg_price:.1f}"
    else:
        blended_price = base_price
        data_source = "commodity benchmark rate"

    # ------------------------------------------------------------------
    # 4. Supply/Demand adjustment → market_trend (per API spec)
    #    INCREASING  = low supply  → +12% scarcity premium
    #    DECREASING  = high supply → -8% surplus discount
    #    STABLE      = balanced    → +2% fair-market nudge
    # ------------------------------------------------------------------
    if total_market_supply < 300:
        market_trend = "INCREASING"
        adjustment_factor = 1.12
        supply_note = (
            f"Low market supply ({total_market_supply:.0f} {request.unit} listed) "
            "signals strong buyer demand — 12% scarcity premium applied."
        )
    elif total_market_supply > 2000:
        market_trend = "DECREASING"
        adjustment_factor = 0.92
        supply_note = (
            f"High market supply ({total_market_supply:.0f} {request.unit} listed). "
            "Competitive pricing recommended for faster clearance (−8% adjustment)."
        )
    else:
        market_trend = "STABLE"
        adjustment_factor = 1.02
        supply_note = (
            f"Balanced market supply ({total_market_supply:.0f} {request.unit} listed). "
            "Fair direct-to-consumer pricing recommended."
        )

    suggested_price = round(blended_price * adjustment_factor, 2)
    min_price = round(suggested_price * 0.88, 2)   # −12% floor
    max_price = round(suggested_price * 1.15, 2)   # +15% ceiling

    # Direct farm-to-buyer saves ~25–30% middleman cut
    potential_margin_pct = round(
        ((suggested_price - suggested_price * 0.65) / suggested_price) * 100, 1
    )

    reasoning = (
        f"Price estimated using {data_source} as reference anchor. "
        f"{supply_note} "
        f"Selling directly on KisanConnect eliminates middlemen, yielding an "
        f"estimated {potential_margin_pct}% margin over farm-gate cost. "
        f"Suggested range: \u20b9{min_price}\u2013\u20b9{max_price} per {request.unit}."
    )

    return schemas.PriceSuggestResponse(
        crop_name=request.crop_name,
        category=request.category,
        suggested_price=suggested_price,
        min_price=min_price,
        max_price=max_price,
        market_trend=market_trend,
        potential_margin_pct=potential_margin_pct,
        reasoning=reasoning,
    )
