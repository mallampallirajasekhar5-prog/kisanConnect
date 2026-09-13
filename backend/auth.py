from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import database
import models
import schemas

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory store for Demo OTPs (for development/demo purposes)
# Default demo OTP is "123456"
DEMO_OTP_STORE = {}
DEMO_DEFAULT_OTP = "123456"


@router.post("/send-otp", response_model=schemas.SendOTPResponse)
def send_otp(request: schemas.SendOTPRequest):
    """
    DEMO AUTHENTICATION: Send OTP API
    Generates and stores a demo OTP ("123456") for the provided 10-digit mobile number.
    """
    mobile = request.mobile
    
    # Store demo OTP
    DEMO_OTP_STORE[mobile] = DEMO_DEFAULT_OTP
    
    return {
        "message": f"Demo OTP sent successfully to {mobile}. Use OTP: {DEMO_DEFAULT_OTP}",
        "otp": DEMO_DEFAULT_OTP
    }


@router.post("/verify-otp", response_model=schemas.VerifyOTPResponse)
def verify_otp(request: schemas.VerifyOTPRequest, db: Session = Depends(database.get_db)):
    """
    DEMO AUTHENTICATION: Verify OTP & User Login / Registration API
    Verifies the demo OTP. Creates user if not present, returns user details and demo token.
    """
    mobile = request.mobile
    otp = request.otp.strip()
    
    # Check if OTP matches demo OTP
    expected_otp = DEMO_OTP_STORE.get(mobile, DEMO_DEFAULT_OTP)
    if otp != expected_otp and otp != DEMO_DEFAULT_OTP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP. Please enter demo OTP '123456'."
        )
    
    # Check if user already exists in DB
    user = db.query(models.User).filter(models.User.mobile == mobile).first()
    
    if not user:
        # Create new user
        user_role = request.role.value if hasattr(request.role, 'value') else str(request.role)
        user_name = request.name if request.name else f"User {mobile[-4:]}"
        
        user = models.User(
            name=user_name,
            mobile=mobile,
            role=user_role
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        message = "User registered and logged in successfully"
    else:
        # Existing user login
        message = "Login successful"

    # Generate a simple demo authentication token
    demo_token = f"demo-token-{user.id}-{user.mobile}"

    return {
        "message": message,
        "token": demo_token,
        "user": user
    }
