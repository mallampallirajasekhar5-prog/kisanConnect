import re
from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, field_validator, Field


class RoleEnum(str, Enum):
    FARMER = "farmer"
    BUYER = "buyer"


class OrderStatusEnum(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    PREPARING = "PREPARING"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DeliveryStatusEnum(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class HealthResponse(BaseModel):
    status: str
    database: str


class WelcomeResponse(BaseModel):
    message: str
    version: str


# --- USER SCHEMAS ---

class SendOTPRequest(BaseModel):
    mobile: str

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\d{10}$", v):
            raise ValueError("Mobile number must contain exactly 10 digits")
        return v


class SendOTPResponse(BaseModel):
    message: str
    debug_otp: Optional[str] = None   # Only populated in development mode; None in production
    cooldown_seconds: int = 60


class VerifyOTPRequest(BaseModel):
    mobile: str
    otp: str
    name: Optional[str] = None
    role: RoleEnum = RoleEnum.BUYER

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\d{10}$", v):
            raise ValueError("Mobile number must contain exactly 10 digits")
        return v


class UserResponse(BaseModel):
    id: int
    name: str
    mobile: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class VerifyOTPResponse(BaseModel):
    message: str
    token: str
    user: UserResponse


# --- PRODUCT SCHEMAS ---

class ProductBase(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    quantity: float
    unit: str
    price: float
    location: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Product name cannot be empty")
        return v.strip()

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Unit cannot be empty (e.g. 'kg', 'quintal')")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Quantity must be greater than 0")
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Price must be greater than 0")
        return v


class ProductCreate(ProductBase):
    farmer_id: int


class ProductResponse(ProductBase):
    id: int
    farmer_id: int
    farmer_name: Optional[str] = None
    created_at: datetime
    is_available: bool

    class Config:
        from_attributes = True


# --- CART SCHEMAS ---

class CartItemCreate(BaseModel):
    buyer_id: int
    product_id: int
    quantity: float

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Quantity must be greater than 0")
        return v


class CartItemUpdate(BaseModel):
    quantity: float

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Quantity must be greater than 0")
        return v


class CartItemDetailResponse(BaseModel):
    cart_item_id: int
    product_id: int
    product_name: str
    farmer_id: int
    price: float
    quantity: float
    unit: str
    item_total: float

    class Config:
        from_attributes = True


class CartSummaryResponse(BaseModel):
    items: List[CartItemDetailResponse]
    total_amount: float


# --- ORDER SCHEMAS ---

class OrderCreate(BaseModel):
    buyer_id: int
    delivery_address: str

    @field_validator("delivery_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Delivery address cannot be empty")
        return v.strip()


class OrderStatusUpdate(BaseModel):
    status: OrderStatusEnum


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    farmer_id: int
    product_name: str
    quantity: float
    unit: str
    price: float
    item_total: float

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    order_id: int
    buyer_id: int
    total_amount: float
    status: str
    delivery_address: str
    created_at: datetime
    items: List[OrderItemResponse]

    class Config:
        from_attributes = True


# --- DELIVERY SCHEMAS ---

class DeliveryCreate(BaseModel):
    order_id: int
    delivery_address: str
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None

    @field_validator("delivery_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Delivery address cannot be empty")
        return v.strip()


class DeliveryUpdateInfo(BaseModel):
    delivery_address: Optional[str] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None


class DeliveryStatusUpdate(BaseModel):
    status: DeliveryStatusEnum


class DeliveryResponse(BaseModel):
    delivery_id: int
    order_id: int
    buyer_id: int
    farmer_id: int
    delivery_address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: str
    estimated_minutes: int
    distance_km: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- AI FEATURE SCHEMAS ---

class RouteOptimizeRequest(BaseModel):
    origin_address: Optional[str] = "Farm Collection Point"
    origin_latitude: float = 16.5062
    origin_longitude: float = 80.6480
    destination_address: str = "Buyer Delivery Destination"
    destination_latitude: float = 16.7235
    destination_longitude: float = 82.1980
    delivery_id: Optional[int] = None


class RouteWayPoint(BaseModel):
    step: int
    instruction: str
    distance_km: float


class RouteOptimizeResponse(BaseModel):
    distance_km: float
    estimated_minutes: int
    origin: str
    destination: str
    directions: List[str]
    waypoints: List[RouteWayPoint]
    delivery_id: Optional[int] = None


class PriceSuggestRequest(BaseModel):
    crop_name: str
    category: str
    quantity: float
    unit: str = "kg"
    location: Optional[str] = "Amalapuram"
    current_price: Optional[float] = None


class PriceSuggestResponse(BaseModel):
    crop_name: str
    category: str
    suggested_price: float
    min_price: float
    max_price: float
    market_trend: str
    potential_margin_pct: float
    reasoning: str


class DemandForecastRequest(BaseModel):
    category: str
    crop_name: Optional[str] = None
    days: Optional[int] = 30


class DemandForecastResponse(BaseModel):
    category: str
    crop_name: Optional[str] = None
    forecast_level: str  # "HIGH", "MEDIUM", "LOW"
    trend_direction: str  # "INCREASING", "STABLE", "DECREASING"
    predicted_quantity_demand: float
    confidence_score: float
    recommendation: str
