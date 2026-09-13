from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import database
import models
import schemas

router = APIRouter(prefix="/cart", tags=["Cart"])


def verify_buyer(buyer_id: int, db: Session) -> models.User:
    """Helper to verify buyer existence and role constraint."""
    buyer = db.query(models.User).filter(models.User.id == buyer_id).first()
    if not buyer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {buyer_id} not found."
        )

    if str(buyer.role).lower() != "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only buyers can manage cart"
        )
    return buyer


@router.post("", response_model=schemas.CartSummaryResponse, status_code=status.HTTP_200_OK)
@router.post("/", response_model=schemas.CartSummaryResponse, status_code=status.HTTP_200_OK)
def add_to_cart(cart_in: schemas.CartItemCreate, db: Session = Depends(database.get_db)):
    """
    ADD PRODUCT TO CART API
    Only users with role='buyer' are allowed. Updates quantity if item already exists in cart.
    """
    # 1. Verify buyer role
    buyer = verify_buyer(cart_in.buyer_id, db)

    # 2. Verify product existence and availability
    product = db.query(models.Product).filter(models.Product.id == cart_in.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {cart_in.product_id} not found."
        )

    if not product.is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product '{product.name}' is currently unavailable."
        )

    # 3. Check for existing cart item
    existing_item = db.query(models.CartItem).filter(
        models.CartItem.buyer_id == cart_in.buyer_id,
        models.CartItem.product_id == cart_in.product_id
    ).first()

    current_qty_in_cart = existing_item.quantity if existing_item else 0.0
    new_total_qty = current_qty_in_cart + cart_in.quantity

    # 4. Check stock availability
    if new_total_qty > product.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested quantity ({new_total_qty} {product.unit}) exceeds available stock ({product.quantity} {product.unit})."
        )

    # 5. Add or update cart item
    if existing_item:
        existing_item.quantity = new_total_qty
    else:
        new_item = models.CartItem(
            buyer_id=cart_in.buyer_id,
            product_id=cart_in.product_id,
            quantity=cart_in.quantity
        )
        db.add(new_item)

    db.commit()

    # 6. Return updated cart summary
    return get_buyer_cart(buyer_id=cart_in.buyer_id, db=db)


@router.get("/{buyer_id}", response_model=schemas.CartSummaryResponse)
def get_buyer_cart(buyer_id: int, db: Session = Depends(database.get_db)):
    """
    VIEW BUYER CART API
    Returns the complete list of cart items and total order calculation for the specified buyer.
    """
    # Verify buyer role
    buyer = verify_buyer(buyer_id, db)

    cart_items = db.query(models.CartItem).filter(models.CartItem.buyer_id == buyer_id).all()

    items_response = []
    total_amount = 0.0

    for item in cart_items:
        product = item.product
        item_total = round(product.price * item.quantity, 2)
        total_amount += item_total

        items_response.append(schemas.CartItemDetailResponse(
            cart_item_id=item.id,
            product_id=product.id,
            product_name=product.name,
            farmer_id=product.farmer_id,
            price=product.price,
            quantity=item.quantity,
            unit=product.unit,
            item_total=item_total
        ))

    return schemas.CartSummaryResponse(
        items=items_response,
        total_amount=round(total_amount, 2)
    )


@router.delete("/item/{cart_item_id}")
def remove_cart_item(cart_item_id: int, db: Session = Depends(database.get_db)):
    """
    REMOVE ITEM FROM CART API
    Deletes a specific cart item by ID.
    """
    cart_item = db.query(models.CartItem).filter(models.CartItem.id == cart_item_id).first()
    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cart item with ID {cart_item_id} not found."
        )

    buyer_id = cart_item.buyer_id
    db.delete(cart_item)
    db.commit()

    return {"message": f"Cart item {cart_item_id} removed successfully", "buyer_id": buyer_id}


@router.delete("/{buyer_id}")
def clear_buyer_cart(buyer_id: int, db: Session = Depends(database.get_db)):
    """
    CLEAR BUYER CART API
    Empties all items from the specified buyer's shopping cart.
    """
    buyer = verify_buyer(buyer_id, db)

    deleted_count = db.query(models.CartItem).filter(models.CartItem.buyer_id == buyer_id).delete()
    db.commit()

    return {"message": f"Cart cleared for buyer {buyer_id}", "deleted_items_count": deleted_count}
