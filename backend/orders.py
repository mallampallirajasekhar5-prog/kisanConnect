from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import database
import models
import schemas

router = APIRouter(prefix="/orders", tags=["Orders"])


def format_order_response(order: models.Order) -> schemas.OrderResponse:
    """Helper to convert Order model to OrderResponse schema."""
    items_response = [
        schemas.OrderItemResponse(
            id=item.id,
            product_id=item.product_id,
            farmer_id=item.farmer_id,
            product_name=item.product_name,
            quantity=item.quantity,
            unit=item.unit,
            price=item.price,
            item_total=item.item_total
        )
        for item in order.items
    ]

    return schemas.OrderResponse(
        order_id=order.id,
        buyer_id=order.buyer_id,
        total_amount=order.total_amount,
        status=order.status,
        delivery_address=order.delivery_address,
        created_at=order.created_at,
        items=items_response
    )


@router.post("", response_model=schemas.OrderResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=schemas.OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order_in: schemas.OrderCreate, db: Session = Depends(database.get_db)):
    """
    CREATE ORDER FROM CART API
    Converts items in buyer's shopping cart into a confirmed order, deducts product stock, and clears cart.
    """
    # 1. Validate buyer
    buyer = db.query(models.User).filter(models.User.id == order_in.buyer_id).first()
    if not buyer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {order_in.buyer_id} not found."
        )

    if str(buyer.role).lower() != "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only buyers can place orders"
        )

    # 2. Fetch cart items
    cart_items = db.query(models.CartItem).filter(models.CartItem.buyer_id == order_in.buyer_id).all()
    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot place order: Shopping cart is empty."
        )

    # 3. Validate stock availability for all items in cart
    total_amount = 0.0
    for cart_item in cart_items:
        product = cart_item.product
        if not product or not product.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product '{cart_item.product_id}' is no longer available."
            )

        if cart_item.quantity > product.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for '{product.name}'. Requested {cart_item.quantity} {product.unit}, but only {product.quantity} {product.unit} available."
            )

        total_amount += round(product.price * cart_item.quantity, 2)

    # 4. Create Order row
    db_order = models.Order(
        buyer_id=order_in.buyer_id,
        total_amount=round(total_amount, 2),
        status=models.OrderStatus.PLACED.value,
        delivery_address=order_in.delivery_address
    )
    db.add(db_order)
    db.flush()  # Assigns db_order.id

    # 5. Create OrderItems & deduct stock
    for cart_item in cart_items:
        product = cart_item.product
        item_total = round(product.price * cart_item.quantity, 2)

        order_item = models.OrderItem(
            order_id=db_order.id,
            product_id=product.id,
            farmer_id=product.farmer_id,
            product_name=product.name,
            quantity=cart_item.quantity,
            unit=product.unit,
            price=product.price,
            item_total=item_total
        )
        db.add(order_item)

        # Deduct product stock
        product.quantity -= cart_item.quantity
        if product.quantity <= 0:
            product.quantity = 0
            product.is_available = False

    # 6. Clear buyer's cart
    db.query(models.CartItem).filter(models.CartItem.buyer_id == order_in.buyer_id).delete()

    db.commit()
    db.refresh(db_order)

    return format_order_response(db_order)


@router.get("/buyer/{buyer_id}", response_model=List[schemas.OrderResponse])
def get_buyer_orders(buyer_id: int, db: Session = Depends(database.get_db)):
    """
    VIEW BUYER ORDERS API
    Returns all orders placed by the specified buyer.
    """
    buyer = db.query(models.User).filter(models.User.id == buyer_id).first()
    if not buyer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {buyer_id} not found."
        )

    orders = db.query(models.Order).filter(models.Order.buyer_id == buyer_id).order_by(models.Order.created_at.desc()).all()
    return [format_order_response(o) for o in orders]


@router.get("/farmer/{farmer_id}", response_model=List[schemas.OrderResponse])
def get_farmer_orders(farmer_id: int, db: Session = Depends(database.get_db)):
    """
    VIEW FARMER ORDERS API
    Returns all orders containing products belonging to the specified farmer.
    """
    farmer = db.query(models.User).filter(models.User.id == farmer_id).first()
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer with ID {farmer_id} not found."
        )

    # Query orders containing order items for this farmer
    orders = db.query(models.Order).join(models.OrderItem).filter(
        models.OrderItem.farmer_id == farmer_id
    ).order_by(models.Order.created_at.desc()).distinct().all()

    return [format_order_response(o) for o in orders]


@router.get("/{order_id}", response_model=schemas.OrderResponse)
def get_order_by_id(order_id: int, db: Session = Depends(database.get_db)):
    """
    VIEW SINGLE ORDER DETAILS API
    Returns order details by order ID.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {order_id} not found."
        )

    return format_order_response(order)


@router.put("/{order_id}/status", response_model=schemas.OrderResponse)
def update_order_status(order_id: int, status_in: schemas.OrderStatusUpdate, db: Session = Depends(database.get_db)):
    """
    UPDATE ORDER STATUS API
    Updates order status (e.g. PLACED -> CONFIRMED -> PREPARING -> OUT_FOR_DELIVERY -> DELIVERED / CANCELLED).
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {order_id} not found."
        )

    order.status = status_in.status.value
    db.commit()
    db.refresh(order)

    return format_order_response(order)
