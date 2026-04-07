"""Authentication routes compatible with frontend API contract."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_from_header
from models.database import User, get_db
from services.auth_service import AuthService
from services.auth_utils import AuthUtils
from services.storage_service import StorageService

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = 5
pending_profile_store: dict[str, dict] = {}


class RegisterRequest(BaseModel):
    firstName: str
    lastName: str = ""
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: Optional[str] = None


class OtpRequest(BaseModel):
    email: str


class VerifyOtpRequest(BaseModel):
    email: str
    otp: str


def _issue_token_for_user(user: User) -> str:
    return AuthUtils.create_access_token(
        {
            "user_id": user.user_id,
            "sub": user.user_id,
            "email": user.email,
        }
    )


def _send_supabase_email_otp(email: str, should_create_user: bool) -> None:
    """Send OTP using Supabase Auth email OTP."""
    client = StorageService._get_client()
    payload = {
        "email": email,
        "options": {
            "should_create_user": should_create_user,
        },
    }
    client.auth.sign_in_with_otp(payload)


@router.post("/send-otp")
async def send_otp(request: OtpRequest):
    """Send OTP to user's email via Supabase Auth."""
    email = request.email.lower().strip()

    try:
        should_create_user = email in pending_profile_store
        _send_supabase_email_otp(email, should_create_user=should_create_user)
        return {"message": "OTP sent to your email."}
    except Exception as e:
        logger.error("Failed to send OTP email to %s: %s", email, str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Unable to send OTP email. Please try again later.") from e


@router.post("/verify-otp")
async def verify_otp(request: VerifyOtpRequest, db: Session = Depends(get_db)):
    """Verify Supabase OTP and return token + user payload."""
    email = request.email.lower().strip()
    try:
        client = StorageService._get_client()
        verify_response = client.auth.verify_otp(
            {
                "email": email,
                "token": str(request.otp).strip(),
                "type": "email",
            }
        )

        session = getattr(verify_response, "session", None)
        supabase_user = getattr(verify_response, "user", None)
        if not supabase_user:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

        user_id = getattr(supabase_user, "id", None)
        user_email = getattr(supabase_user, "email", None) or email
        if not user_id:
            raise HTTPException(status_code=400, detail="Could not verify user identity.")

        user, error = AuthService.get_or_create_user_from_token(user_id, user_email, db)
        if error or not user:
            raise HTTPException(status_code=500, detail=error or "Unable to sync user profile")

        pending_profile = pending_profile_store.pop(email, None)
        if pending_profile:
            updates = {
                "first_name": pending_profile.get("first_name") or user.first_name,
                "last_name": pending_profile.get("last_name") or user.last_name,
                "profile_data": dict(user.profile_data or {}),
            }
            updates["profile_data"]["authProvider"] = "email_otp"
            updates["profile_data"]["profileComplete"] = bool(updates["first_name"])
            updated_user, _ = AuthService.update_user_profile(user.user_id, updates, db)
            if updated_user:
                user = updated_user

        token = getattr(session, "access_token", None)
        if not token:
            token = _issue_token_for_user(user)

        return {"token": token, "user": AuthService.serialize_user(user)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OTP verification failed for %s: %s", email, str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.") from e


@router.post("/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Prepare signup profile details before OTP verification."""
    email = request.email.lower().strip()
    pending_profile_store[email] = {
        "first_name": request.firstName.strip(),
        "last_name": (request.lastName or "").strip(),
        "created_at": datetime.now(tz=timezone.utc),
        "expires_at": datetime.now(tz=timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES),
    }
    return {"message": "Registration initiated. Please verify OTP sent to your email."}


@router.post("/login")
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """OTP-first login trigger endpoint (email only)."""
    email = request.email.lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # If we already know this user locally, keep it as login-only OTP.
    known_user = AuthService.get_user_by_email(email, db)
    should_create_user = known_user is None and email in pending_profile_store

    try:
        _send_supabase_email_otp(email, should_create_user=should_create_user)
        return {"message": "OTP sent to your email."}
    except Exception as e:
        logger.error("Failed to send login OTP to %s: %s", email, str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Unable to send OTP email. Please try again later.") from e


@router.get("/me")
async def me(current_user: User = Depends(get_current_user_from_header)):
    """Get authenticated user details."""
    return {"user": AuthService.serialize_user(current_user)}


@router.delete("/delete")
async def delete_account(
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Delete authenticated account and related records."""
    success, error = AuthService.delete_user(current_user.user_id, db)
    if not success:
        raise HTTPException(status_code=500, detail=error or "Error deleting account.")
    return {"message": "Account deleted successfully."}


@router.get("/google")
async def google_oauth_not_configured():
    """Placeholder endpoint for Google OAuth migration.

    Keeps the frontend route functional while OAuth provider setup is pending.
    """
    raise HTTPException(
        status_code=501,
        detail="Google OAuth is not configured on the FastAPI backend yet.",
    )
