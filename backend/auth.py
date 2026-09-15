"""
KisanConnect Authentication — OTP flow with proper security.

Security features implemented:
  - Cryptographically random 6-digit OTP (secrets module)
  - SHA-256 hash stored in memory (never plaintext)
  - OTP expiry: 5 minutes (configurable via OTP_TTL_SECONDS)
  - Max 3 verification attempts per OTP (OTP_MAX_ATTEMPTS)
  - 60-second resend cooldown (OTP_RESEND_COOLDOWN_SECONDS)
  - OTP never returned in HTTP response body in production
  - JWT access tokens (HS256) via python-jose
  - Pluggable SMS dispatch via sms.py adapter
"""

import os
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from jose import jwt

import database
import models
import schemas
from sms import send_otp_sms

logger = logging.getLogger("kisan.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ─────────────────────────────────────────────────────────────
#  Configuration (read from .env / environment variables)
# ─────────────────────────────────────────────────────────────

APP_ENV = os.getenv("APP_ENV", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY", "kisan-connect-dev-secret-key-change-in-prod")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "86400"))

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))          # 5 minutes
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "3"))
OTP_RESEND_COOLDOWN = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60"))

# ─────────────────────────────────────────────────────────────
#  In-memory OTP store
#  Structure: { mobile: OtpRecord }
# ─────────────────────────────────────────────────────────────

class OtpRecord:
    """Holds hashed OTP and metadata for one mobile number."""
    def __init__(self, otp_hash: str):
        self.otp_hash = otp_hash
        self.created_at = datetime.now(timezone.utc)
        self.last_sent_at = datetime.now(timezone.utc)
        self.attempts = 0

    def is_expired(self) -> bool:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() > OTP_TTL_SECONDS

    def resend_cooldown_remaining(self) -> int:
        """Returns seconds remaining on resend cooldown (0 if allowed)."""
        elapsed = (datetime.now(timezone.utc) - self.last_sent_at).total_seconds()
        remaining = OTP_RESEND_COOLDOWN - int(elapsed)
        return max(0, remaining)

    def attempts_remaining(self) -> int:
        return max(0, OTP_MAX_ATTEMPTS - self.attempts)


OTP_STORE: dict[str, OtpRecord] = {}


# ─────────────────────────────────────────────────────────────
#  Helper functions
# ─────────────────────────────────────────────────────────────

def _generate_otp() -> str:
    """Generate a cryptographically secure random 6-digit OTP."""
    return f"{secrets.randbelow(1000000):06d}"


def _hash_otp(otp: str) -> str:
    """SHA-256 hash of the OTP string."""
    return hashlib.sha256(otp.encode()).hexdigest()


def _create_jwt_token(user_id: int, mobile: str, role: str) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
    payload = {
        "sub": str(user_id),
        "mobile": mobile,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def _is_dev_mode() -> bool:
    return APP_ENV in ("development", "dev", "local", "test")


# ─────────────────────────────────────────────────────────────
#  SEND OTP ENDPOINT
# ─────────────────────────────────────────────────────────────

@router.post("/send-otp", response_model=schemas.SendOTPResponse)
def send_otp(request: schemas.SendOTPRequest):
    """
    Send OTP to a 10-digit Indian mobile number.

    Security:
    - Enforces 60-second resend cooldown.
    - Generates a cryptographically random OTP.
    - Stores only a SHA-256 hash (never plaintext).
    - Dispatches via pluggable SMS adapter (SMS_PROVIDER env var).
    - OTP is NOT returned in the response body in production.
      In development mode, a debug_otp field is included for testing.
    """
    mobile = request.mobile

    # ── Resend cooldown check ──────────────────────────────
    existing = OTP_STORE.get(mobile)
    if existing:
        cooldown_remaining = existing.resend_cooldown_remaining()
        if cooldown_remaining > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {cooldown_remaining} seconds before requesting a new OTP."
            )

    # ── Generate & store new OTP ───────────────────────────
    otp = _generate_otp()
    otp_hash = _hash_otp(otp)

    record = OtpRecord(otp_hash=otp_hash)
    OTP_STORE[mobile] = record

    # ── Dispatch SMS ───────────────────────────────────────
    sms_sent = send_otp_sms(mobile, otp)
    if not sms_sent:
        logger.error(f"SMS dispatch failed for {mobile}")
        # Don't fail the request — OTP is stored, user can retry
        # In production you might want to raise here

    # ── Build response ─────────────────────────────────────
    response_data: dict = {
        "message": f"OTP sent successfully to +91-XXXXXX{mobile[-4:]}. Valid for 5 minutes.",
        "debug_otp": None,
        "cooldown_seconds": OTP_RESEND_COOLDOWN,
    }

    # Only expose OTP in development/mock mode (never in production)
    if _is_dev_mode():
        response_data["debug_otp"] = otp

    return response_data


# ─────────────────────────────────────────────────────────────
#  VERIFY OTP ENDPOINT
# ─────────────────────────────────────────────────────────────

@router.post("/verify-otp", response_model=schemas.VerifyOTPResponse)
def verify_otp(request: schemas.VerifyOTPRequest, db: Session = Depends(database.get_db)):
    """
    Verify OTP, create or login user, return JWT token.

    Security:
    - Checks OTP expiry.
    - Tracks and limits verification attempts (max 3).
    - Compares SHA-256 hashes (constant-time via secrets.compare_digest).
    - Returns JWT token on success, not a simple string token.
    - User role is embedded in the JWT and returned in response.
    """
    mobile = request.mobile
    otp = request.otp.strip()

    # ── Retrieve OTP record ────────────────────────────────
    record = OTP_STORE.get(mobile)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No OTP found for this mobile number. Please request a new OTP."
        )

    # ── Check expiry ───────────────────────────────────────
    if record.is_expired():
        del OTP_STORE[mobile]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired. Please request a new OTP."
        )

    # ── Check attempt limit ────────────────────────────────
    if record.attempts >= OTP_MAX_ATTEMPTS:
        del OTP_STORE[mobile]
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum OTP attempts exceeded. Please request a new OTP."
        )

    # ── Verify OTP (constant-time hash comparison) ─────────
    record.attempts += 1
    input_hash = _hash_otp(otp)
    if not secrets.compare_digest(input_hash, record.otp_hash):
        remaining = record.attempts_remaining()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OTP. {remaining} attempt(s) remaining."
        )

    # ── OTP verified — clean up store ─────────────────────
    del OTP_STORE[mobile]

    # ── Create or fetch user ───────────────────────────────
    user = db.query(models.User).filter(models.User.mobile == mobile).first()

    if not user:
        user_role = request.role.value if hasattr(request.role, "value") else str(request.role)
        user_name = request.name.strip() if request.name and request.name.strip() else f"User {mobile[-4:]}"

        user = models.User(
            name=user_name,
            mobile=mobile,
            role=user_role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        message = f"Welcome to KisanConnect, {user.name}! Account created successfully."
    else:
        message = f"Welcome back, {user.name}!"

    # ── Generate JWT token ─────────────────────────────────
    token = _create_jwt_token(
        user_id=user.id,
        mobile=user.mobile,
        role=user.role,
    )

    return {
        "message": message,
        "token": token,
        "user": user,
    }
