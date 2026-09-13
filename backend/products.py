from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import database
import models
import schemas

router = APIRouter(prefix="/products", tags=["Products"])


@router.post("", response_model=schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(product_in: schemas.ProductCreate, db: Session = Depends(database.get_db)):
    """
    FARMER PRODUCT CREATION API
    Only users registered with role='farmer' are allowed to list products.
    """
    # 1. Verify farmer existence
    farmer = db.query(models.User).filter(models.User.id == product_in.farmer_id).first()
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {product_in.farmer_id} not found."
        )

    # 2. Verify role constraint (Must be a farmer)
    if str(farmer.role).lower() != "farmer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{farmer.name}' has role '{farmer.role}'. Only users with role 'farmer' can add products."
        )

    # 3. Create Product
    db_product = models.Product(
        farmer_id=product_in.farmer_id,
        name=product_in.name,
        category=product_in.category,
        description=product_in.description,
        quantity=product_in.quantity,
        unit=product_in.unit,
        price=product_in.price,
        location=product_in.location,
        is_available=True
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)

    # Prepare response with farmer_name
    res = schemas.ProductResponse.model_validate(db_product)
    res.farmer_name = farmer.name
    return res


@router.get("", response_model=List[schemas.ProductResponse])
@router.get("/", response_model=List[schemas.ProductResponse])
def get_products(
    category: Optional[str] = None,
    location: Optional[str] = None,
    search: Optional[str] = None,
    farmer_id: Optional[int] = None,
    db: Session = Depends(database.get_db)
):
    """
    BROWSE PRODUCTS API (For Buyers & Farmers)
    Returns all available agricultural products with optional filters.
    """
    query = db.query(models.Product).filter(models.Product.is_available == True)

    if category:
        query = query.filter(models.Product.category.ilike(f"%{category}%"))
    if location:
        query = query.filter(models.Product.location.ilike(f"%{location}%"))
    if search:
        query = query.filter(
            (models.Product.name.ilike(f"%{search}%")) | 
            (models.Product.description.ilike(f"%{search}%"))
        )
    if farmer_id:
        query = query.filter(models.Product.farmer_id == farmer_id)

    products = query.order_by(models.Product.created_at.desc()).all()

    result = []
    for p in products:
        p_res = schemas.ProductResponse.model_validate(p)
        if p.farmer:
            p_res.farmer_name = p.farmer.name
        result.append(p_res)

    return result


@router.get("/farmer/{farmer_id}", response_model=List[schemas.ProductResponse])
def get_farmer_products(farmer_id: int, db: Session = Depends(database.get_db)):
    """
    FARMER DASHBOARD PRODUCTS API
    Returns all products added by a specific farmer.
    """
    farmer = db.query(models.User).filter(models.User.id == farmer_id).first()
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer with ID {farmer_id} not found."
        )

    products = db.query(models.Product).filter(models.Product.farmer_id == farmer_id).order_by(models.Product.created_at.desc()).all()

    result = []
    for p in products:
        p_res = schemas.ProductResponse.model_validate(p)
        p_res.farmer_name = farmer.name
        result.append(p_res)

    return result


@router.get("/{product_id}", response_model=schemas.ProductResponse)
def get_product_by_id(product_id: int, db: Session = Depends(database.get_db)):
    """
    VIEW SINGLE PRODUCT API
    Returns product details by product ID.
    """
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found."
        )

    res = schemas.ProductResponse.model_validate(product)
    if product.farmer:
        res.farmer_name = product.farmer.name
    return res
