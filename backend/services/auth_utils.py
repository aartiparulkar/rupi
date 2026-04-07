"""Authentication utilities for password hashing and JWT token management"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
import jwt
from passlib.context import CryptContext
from app.config import settings
from services.storage_service import StorageService

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")


class AuthUtils:
    """Utilities for authentication operations"""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a plain-text password for storage."""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a plain-text password against a stored hash."""
        if not password_hash:
            return False
        return pwd_context.verify(password, password_hash)

    @staticmethod
    def create_access_token(payload: Dict, expires_hours: Optional[int] = None) -> str:
        """Create a signed JWT access token."""
        expiry_hours = expires_hours or settings.jwt_expiration_hours
        now = datetime.now(tz=timezone.utc)
        token_payload = {
            **payload,
            "iat": now,
            "exp": now + timedelta(hours=expiry_hours),
        }
        return jwt.encode(token_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    
    @staticmethod
    def verify_token(token: str) -> Optional[Dict]:
        """Verify a JWT token and return the payload"""
        # First, try local JWT verification for backward compatibility.
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.info(f"Local JWT validation failed, trying Supabase auth: {str(e)}")

        # Fallback to Supabase server-side token validation.
        try:
            try:
                client = StorageService._get_client()
            except Exception:
                return None

            supabase_user_response = client.auth.get_user(token)
            supabase_user = getattr(supabase_user_response, "user", None)
            if not supabase_user:
                return None

            # Normalize payload keys expected by existing backend code.
            user_id = getattr(supabase_user, "id", None)
            email = getattr(supabase_user, "email", None)
            if not user_id:
                return None

            return {
                "user_id": user_id,
                "email": email,
                "iat": datetime.now(tz=timezone.utc),
            }
        except Exception as e:
            logger.warning(f"Supabase token validation failed: {str(e)}")
            return None
