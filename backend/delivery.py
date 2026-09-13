from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import database
import models
import schemas

router = APIRouter(prefix="/delivery", tags=["Delivery"])

# Strict state transition matrix
ALLOWED_TRANSITIONS = {
    "PENDING": ["ASSIGNED", "CANCELLED"],
    "ASSIGNED": ["PICKED_UP", "CANCELLED"],
    "PICKED_UP": ["OUT_FOR_DELIVERY", "CANCELLED"],
    "OUT_FOR_DELIVERY": ["DELIVERED", "CANCELLED"],
    "DELIVERED": [],  # Terminal state
    "CANCELLED": []   # Terminal state
}


def format_delivery_response(d: models.Delivery) -> schemas.DeliveryResponse:
    """Helper to convert Delivery model to DeliveryResponse schema."""
    return schemas.DeliveryResponse(
        delivery_id=d.id,
        order_id=d.order_id,
        buyer_id=d.buyer_id,
        farmer_id=d.farmer_id,
        delivery_address=d.delivery_address,
        latitude=d.delivery_latitude,
        longitude=d.delivery_longitude,
        status=d.status,
        estimated_minutes=d.estimated_minutes,
        distance_km=d.distance_km,
        created_at=d.created_at,
        updated_at=d.updated_at
    )


@router.post("", response_model=schemas.DeliveryResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=schemas.DeliveryResponse, status_code=status.HTTP_201_CREATED)
def create_delivery(delivery_in: schemas.DeliveryCreate, db: Session = Depends(database.get_db)):
    """
    CREATE DELIVERY API
    Creates a new delivery order for an existing confirmed order.
    """
    # 1. Verify order existence
    order = db.query(models.Order).filter(models.Order.id == delivery_in.order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {delivery_in.order_id} not found."
        )

    # 2. Verify order is not CANCELLED
    if str(order.status).upper() == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create delivery for a cancelled order (Order #{delivery_in.order_id})."
        )

    # 3. Check duplicate delivery creation for same order
    existing_delivery = db.query(models.Delivery).filter(models.Delivery.order_id == delivery_in.order_id).first()
    if existing_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Delivery already exists for Order #{delivery_in.order_id} (Delivery ID #{existing_delivery.id})."
        )

    # 4. Extract buyer_id & farmer_id
    buyer_id = order.buyer_id
    if not order.items or len(order.items) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order #{delivery_in.order_id} has no order items."
        )

    farmer_id = order.items[0].farmer_id

    # 5. Create Delivery record with demo distance & time estimates
    delivery_address = delivery_in.delivery_address if delivery_in.delivery_address else order.delivery_address

    db_delivery = models.Delivery(
        order_id=delivery_in.order_id,
        buyer_id=buyer_id,
        farmer_id=farmer_id,
        delivery_address=delivery_address,
        delivery_latitude=delivery_in.delivery_latitude,
        delivery_longitude=delivery_in.delivery_longitude,
        status=models.DeliveryStatus.PENDING.value,
        estimated_minutes=35,  # Demo value (to be replaced by AI route optimizer)
        distance_km=12.5       # Demo value (to be replaced by AI route optimizer)
    )

    db.add(db_delivery)
    db.commit()
    db.refresh(db_delivery)

    return format_delivery_response(db_delivery)


@router.get("/order/{order_id}", response_model=schemas.DeliveryResponse)
def get_delivery_by_order_id(order_id: int, db: Session = Depends(database.get_db)):
    """
    GET DELIVERY BY ORDER ID API
    Retrieves delivery details for a specific order.
    """
    delivery = db.query(models.Delivery).filter(models.Delivery.order_id == order_id).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery for Order #{order_id} not found."
        )
    return format_delivery_response(delivery)


@router.get("/buyer/{buyer_id}", response_model=List[schemas.DeliveryResponse])
def get_deliveries_by_buyer(buyer_id: int, db: Session = Depends(database.get_db)):
    """
    GET DELIVERIES BY BUYER API
    Retrieves all deliveries belonging to a specific buyer.
    """
    deliveries = db.query(models.Delivery).filter(models.Delivery.buyer_id == buyer_id).order_by(models.Delivery.created_at.desc()).all()
    return [format_delivery_response(d) for d in deliveries]


@router.get("/farmer/{farmer_id}", response_model=List[schemas.DeliveryResponse])
def get_deliveries_by_farmer(farmer_id: int, db: Session = Depends(database.get_db)):
    """
    GET DELIVERIES BY FARMER API
    Retrieves all deliveries belonging to a specific farmer's orders.
    """
    deliveries = db.query(models.Delivery).filter(models.Delivery.farmer_id == farmer_id).order_by(models.Delivery.created_at.desc()).all()
    return [format_delivery_response(d) for d in deliveries]


@router.get("/{delivery_id}", response_model=schemas.DeliveryResponse)
def get_delivery_by_id(delivery_id: int, db: Session = Depends(database.get_db)):
    """
    GET DELIVERY BY ID API
    Retrieves delivery details by delivery ID.
    """
    delivery = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery with ID #{delivery_id} not found."
        )
    return format_delivery_response(delivery)


@router.put("/{delivery_id}/status", response_model=schemas.DeliveryResponse)
def update_delivery_status(
    delivery_id: int,
    status_in: schemas.DeliveryStatusUpdate,
    db: Session = Depends(database.get_db)
):
    """
    UPDATE DELIVERY STATUS API
    Validates state machine transitions: PENDING -> ASSIGNED -> PICKED_UP -> OUT_FOR_DELIVERY -> DELIVERED.
    Synchronizes parent Order status when OUT_FOR_DELIVERY or DELIVERED.
    """
    delivery = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery with ID #{delivery_id} not found."
        )

    current_status = str(delivery.status).upper()
    target_status = status_in.status.value.upper()

    # Allow idempotent same status update
    if current_status != target_status:
        allowed = ALLOWED_TRANSITIONS.get(current_status, [])
        if target_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid delivery status transition from '{current_status}' to '{target_status}'. Allowed transitions: {allowed}."
            )

        delivery.status = target_status
        delivery.updated_at = datetime.utcnow()

        # Synchronize Order status
        order = db.query(models.Order).filter(models.Order.id == delivery.order_id).first()
        if order:
            if target_status == "OUT_FOR_DELIVERY":
                order.status = "OUT_FOR_DELIVERY"
            elif target_status == "DELIVERED":
                order.status = "DELIVERED"

        db.commit()
        db.refresh(delivery)

    return format_delivery_response(delivery)


@router.put("/{delivery_id}", response_model=schemas.DeliveryResponse)
def update_delivery_info(
    delivery_id: int,
    info_in: schemas.DeliveryUpdateInfo,
    db: Session = Depends(database.get_db)
):
    """
    UPDATE DELIVERY INFORMATION API
    Allows updating delivery address and latitude/longitude coordinates.
    """
    delivery = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery with ID #{delivery_id} not found."
        )

    if info_in.delivery_address is not None and info_in.delivery_address.strip():
        delivery.delivery_address = info_in.delivery_address.strip()
    if info_in.delivery_latitude is not None:
        delivery.delivery_latitude = info_in.delivery_latitude
    if info_in.delivery_longitude is not None:
        delivery.delivery_longitude = info_in.delivery_longitude

    delivery.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(delivery)

    return format_delivery_response(delivery)
