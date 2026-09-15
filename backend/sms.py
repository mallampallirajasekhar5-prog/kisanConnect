"""
KisanConnect SMS Adapter
========================
Pluggable SMS dispatch layer. Switch providers by setting
SMS_PROVIDER env var — code never needs to change.

Supported providers:
  mock      — logs OTP to console (default, no API key needed)
  fast2sms  — https://www.fast2sms.com  (recommended for SIH/India)
  twilio    — https://www.twilio.com
  msg91     — https://msg91.com
"""

import os
import logging

logger = logging.getLogger("kisan.sms")


def send_otp_sms(mobile: str, otp: str) -> bool:
    """
    Dispatch OTP SMS via the configured provider.
    Returns True on success, False on failure.
    mobile: 10-digit Indian mobile number (no country code stored internally)
    """
    provider = os.getenv("SMS_PROVIDER", "mock").lower().strip()

    if provider == "mock":
        return _send_mock(mobile, otp)
    elif provider == "fast2sms":
        return _send_fast2sms(mobile, otp)
    elif provider == "twilio":
        return _send_twilio(mobile, otp)
    elif provider == "msg91":
        return _send_msg91(mobile, otp)
    else:
        logger.warning(f"Unknown SMS_PROVIDER='{provider}'. Falling back to mock.")
        return _send_mock(mobile, otp)


# ─────────────────────────────────────────────────────────────
#  MOCK PROVIDER (development / testing)
# ─────────────────────────────────────────────────────────────

def _send_mock(mobile: str, otp: str) -> bool:
    """Print OTP to server logs only — never returned in HTTP response."""
    logger.info(f"[MOCK SMS] Mobile: {mobile} | OTP: {otp}")
    print(f"\n{'='*50}")
    print(f"  [DEV MODE] OTP for {mobile}: {otp}")
    print(f"{'='*50}\n")
    return True


# ─────────────────────────────────────────────────────────────
#  FAST2SMS PROVIDER (India — recommended for SIH)
# ─────────────────────────────────────────────────────────────

def _send_fast2sms(mobile: str, otp: str) -> bool:
    """
    Fast2SMS Quick SMS (DLT-free route for OTPs).
    Docs: https://docs.fast2sms.com/#send-message
    Requires FAST2SMS_API_KEY env var.
    """
    api_key = os.getenv("FAST2SMS_API_KEY", "")
    if not api_key:
        logger.error("FAST2SMS_API_KEY is not set. Cannot send SMS.")
        return False

    try:
        import httpx
        message = f"Your KisanConnect OTP is {otp}. Valid for 5 minutes. Do not share this OTP. - KisanConnect"
        url = "https://www.fast2sms.com/dev/bulkV2"
        headers = {
            "authorization": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "route": "q",           # Quick SMS route (no DLT registration needed)
            "message": message,
            "language": "english",
            "flash": 0,
            "numbers": mobile,
        }
        response = httpx.post(url, json=payload, headers=headers, timeout=10)
        result = response.json()

        if response.status_code == 200 and result.get("return") is True:
            logger.info(f"Fast2SMS OTP sent successfully to {mobile}")
            return True
        else:
            logger.error(f"Fast2SMS error: {result}")
            return False

    except Exception as e:
        logger.error(f"Fast2SMS exception: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  TWILIO PROVIDER
# ─────────────────────────────────────────────────────────────

def _send_twilio(mobile: str, otp: str) -> bool:
    """
    Twilio SMS provider.
    Requires: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_FROM_NUMBER", "")

    if not all([account_sid, auth_token, from_number]):
        logger.error("Twilio credentials not fully set. Check TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER.")
        return False

    try:
        import httpx, base64
        to_number = f"+91{mobile}"
        message = f"Your KisanConnect OTP is {otp}. Valid for 5 minutes. Do not share. - KisanConnect"
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}
        payload = {"From": from_number, "To": to_number, "Body": message}

        response = httpx.post(url, data=payload, headers=headers, timeout=10)
        if response.status_code in (200, 201):
            logger.info(f"Twilio OTP sent successfully to {mobile}")
            return True
        else:
            logger.error(f"Twilio error {response.status_code}: {response.text}")
            return False

    except Exception as e:
        logger.error(f"Twilio exception: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  MSG91 PROVIDER
# ─────────────────────────────────────────────────────────────

def _send_msg91(mobile: str, otp: str) -> bool:
    """
    MSG91 Send OTP API.
    Requires: MSG91_AUTH_KEY, MSG91_SENDER_ID, MSG91_ROUTE
    """
    auth_key = os.getenv("MSG91_AUTH_KEY", "")
    sender_id = os.getenv("MSG91_SENDER_ID", "KISANC")
    route = os.getenv("MSG91_ROUTE", "4")

    if not auth_key:
        logger.error("MSG91_AUTH_KEY is not set. Cannot send SMS.")
        return False

    try:
        import httpx
        message = f"Your KisanConnect OTP is {otp}. Valid for 5 minutes. - KisanConnect"
        url = "https://api.msg91.com/api/sendotp.php"
        params = {
            "authkey": auth_key,
            "mobile": f"91{mobile}",
            "message": message,
            "sender": sender_id,
            "otp": otp,
            "otp_expiry": 5,
        }
        response = httpx.get(url, params=params, timeout=10)
        result = response.json()

        if response.status_code == 200 and result.get("type") == "success":
            logger.info(f"MSG91 OTP sent successfully to {mobile}")
            return True
        else:
            logger.error(f"MSG91 error: {result}")
            return False

    except Exception as e:
        logger.error(f"MSG91 exception: {e}")
        return False
