"""Authentication utilities for password hashing and JWT token management"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
import socket
import jwt
from passlib.context import CryptContext
from app.config import settings
from services.storage_service import StorageService

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")


class AuthUtils:
    """Utilities for authentication operations"""

    @staticmethod
    def _normalize_payload(payload: Dict) -> Optional[Dict]:
        """Normalize token claims to backend's expected payload shape."""
        if not payload:
            return None

        user_id = payload.get("user_id") or payload.get("sub") or payload.get("id")
        if not user_id:
            return None

        normalized = dict(payload)
        normalized["user_id"] = user_id
        return normalized

    @staticmethod
    def _decode_with_secret(token: str, secret: str) -> Optional[Dict]:
        """Decode JWT using a shared secret and normalize output claims."""
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
        return AuthUtils._normalize_payload(payload)

    @staticmethod
    def _decode_unverified_payload(token: str) -> Optional[Dict]:
        """Decode JWT payload without verifying the signature.

        This is used only to inspect claims like `exp` so expired tokens can be
        rejected before any remote Supabase validation is attempted.
        """
        try:
            payload = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                },
            )
        except Exception:
            return None

        return AuthUtils._normalize_payload(payload)

    @staticmethod
    def _is_expired_claim(payload: Optional[Dict]) -> bool:
        """Return True when a JWT payload has an expired `exp` claim."""
        if not payload:
            return False

        exp = payload.get("exp")
        if exp is None:
            return False

        try:
            exp_timestamp = datetime.fromtimestamp(int(exp), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return False

        return datetime.now(tz=timezone.utc) >= exp_timestamp

    @staticmethod
    def _decode_unverified_dev_fallback(token: str) -> Optional[Dict]:
        """Development-only fallback for temporary Supabase connectivity failures."""
        if str(settings.environment).lower() == "production":
            return None

        try:
            payload = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": True,
                    "verify_aud": False,
                },
            )
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except Exception:
            return None

        normalized = AuthUtils._normalize_payload(payload)
        if normalized:
            logger.warning("Using development fallback token validation without signature verification")
        return normalized

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
        unverified_payload = AuthUtils._decode_unverified_payload(token)
        if AuthUtils._is_expired_claim(unverified_payload):
            logger.warning("Token has expired")
            return None

        # First, try app-local JWT verification.
        try:
            payload = AuthUtils._decode_with_secret(token, settings.jwt_secret_key)
            if payload:
                return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Local JWT validation failed, trying Supabase secret/auth: {str(e)}")

        # Next, try Supabase JWT secret verification (offline) if configured.
        if settings.supabase_jwt_secret and settings.supabase_jwt_secret != settings.jwt_secret_key:
            try:
                payload = AuthUtils._decode_with_secret(token, settings.supabase_jwt_secret)
                if payload:
                    return payload
            except jwt.ExpiredSignatureError:
                logger.warning("Token has expired")
                return None
            except jwt.InvalidTokenError as e:
                logger.debug(f"Supabase JWT secret validation failed, trying Supabase auth API: {str(e)}")

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

            return AuthUtils._normalize_payload({
                "user_id": user_id,
                "email": email,
                "iat": datetime.now(tz=timezone.utc),
            })
        except (socket.gaierror, OSError) as e:
            logger.warning(f"Supabase token validation failed due to network/DNS: {str(e)}")
            fallback_payload = AuthUtils._decode_unverified_dev_fallback(token)
            if fallback_payload:
                return fallback_payload
            return None
        except Exception as e:
            logger.warning(f"Supabase token validation failed: {str(e)}")
            fallback_payload = AuthUtils._decode_unverified_dev_fallback(token)
            if fallback_payload:
                return fallback_payload
            return None
