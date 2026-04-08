"""Authentication service for user management"""

import logging
import uuid
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError
from models.database import User

logger = logging.getLogger(__name__)


class AuthService:
    """Service for user authentication and management"""

    @staticmethod
    def _ensure_users_table(db: Session) -> None:
        """Create users table if it does not exist yet."""
        bind = db.get_bind()
        User.__table__.create(bind=bind, checkfirst=True)

    @staticmethod
    def _is_missing_users_table_error(error: Exception) -> bool:
        if not isinstance(error, ProgrammingError):
            return False
        original = getattr(error, "orig", None)
        pgcode = getattr(original, "pgcode", None)
        if pgcode == "42P01":
            return True
        return "relation \"users\" does not exist" in str(error).lower()
    
    @staticmethod
    def get_user_by_id(user_id: str, db: Session) -> Optional[User]:
        """Get user by user ID"""
        try:
            return db.query(User).filter_by(user_id=user_id).first()
        except Exception as e:
            if AuthService._is_missing_users_table_error(e):
                db.rollback()
                AuthService._ensure_users_table(db)
                return db.query(User).filter_by(user_id=user_id).first()
            raise

    @staticmethod
    def get_user_by_email(email: str, db: Session) -> Optional[User]:
        """Get user by normalized email."""
        normalized_email = email.lower().strip()
        try:
            return db.query(User).filter_by(email=normalized_email).first()
        except Exception as e:
            if AuthService._is_missing_users_table_error(e):
                db.rollback()
                AuthService._ensure_users_table(db)
                return db.query(User).filter_by(email=normalized_email).first()
            raise

    @staticmethod
    def create_user(
        email: str,
        first_name: str,
        last_name: str,
        password_hash: str,
        db: Session,
    ) -> tuple[Optional[User], Optional[str]]:
        """Create a new user account."""
        try:
            normalized_email = email.lower().strip()
            try:
                existing = db.query(User).filter_by(email=normalized_email).first()
            except Exception as e:
                if AuthService._is_missing_users_table_error(e):
                    db.rollback()
                    AuthService._ensure_users_table(db)
                    existing = db.query(User).filter_by(email=normalized_email).first()
                else:
                    raise
            if existing:
                return None, "An account with this email already exists."

            user = User(
                user_id=str(uuid.uuid4()),
                email=normalized_email,
                first_name=first_name.strip(),
                last_name=(last_name or "").strip(),
                password_hash=password_hash,
                is_active=True,
                is_verified=True,
                profile_data={"profileComplete": False, "authProvider": "email"},
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user, None
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating user: {str(e)}", exc_info=True)
            return None, "Server error during registration."

    @staticmethod
    def delete_user(user_id: str, db: Session) -> tuple[bool, Optional[str]]:
        """Delete a user and related data."""
        try:
            from models.database import ChatMessage, ChatSession, DocumentUpload, UserCalculations

            user = db.query(User).filter_by(user_id=user_id).first()
            if not user:
                return False, "User not found"

            user_sessions = db.query(ChatSession).filter_by(user_id=user_id).all()
            session_ids = [session.session_id for session in user_sessions]
            if session_ids:
                db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
            db.query(ChatSession).filter_by(user_id=user_id).delete(synchronize_session=False)
            db.query(DocumentUpload).filter_by(user_id=user_id).delete(synchronize_session=False)
            db.query(UserCalculations).filter_by(user_id=user_id).delete(synchronize_session=False)
            db.delete(user)
            db.commit()
            return True, None
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting user: {str(e)}", exc_info=True)
            return False, "Error deleting account."

    @staticmethod
    def serialize_user(user: User) -> dict:
        """Serialize user into frontend-compatible camelCase shape."""
        profile_data = user.profile_data if isinstance(user.profile_data, dict) else {}
        return {
            "id": user.user_id,
            "userId": user.user_id,
            "email": user.email,
            "firstName": user.first_name or "",
            "lastName": user.last_name or "",
            "profileComplete": bool(profile_data.get("profileComplete", False)),
            "authProvider": profile_data.get("authProvider", "email"),
            "dob": profile_data.get("dob", ""),
            "gender": profile_data.get("gender", ""),
            "profession": profile_data.get("profession", ""),
            "pan": profile_data.get("pan", ""),
            "incomeRange": profile_data.get("incomeRange", ""),
            "taxRegime": profile_data.get("taxRegime", ""),
            "riskAppetite": profile_data.get("riskAppetite", ""),
            "goals": profile_data.get("goals", []),
            "phone": profile_data.get("phone", ""),
            "city": profile_data.get("city", ""),
            "state": profile_data.get("state", ""),
            "address": profile_data.get("address", ""),
            "itrProfile": profile_data.get("itr_profile", {}),
            "mfaEnabled": bool(profile_data.get("mfaEnabled", False)),
            "loginNotifications": bool(profile_data.get("loginNotifications", True)),
        }

    @staticmethod
    def get_or_create_user_from_token(user_id: str, email: Optional[str], db: Session) -> tuple[Optional[User], Optional[str]]:
        """Fetch user by token identity, creating a lightweight profile when missing."""
        try:
            user = db.query(User).filter_by(user_id=user_id).first()
            if user:
                # Keep email current when upstream auth provider updates it.
                if email and user.email != email:
                    user.email = email
                    db.commit()
                    db.refresh(user)
                return user, None

            if not email:
                return None, "Email missing in token payload"

            local_part = email.split("@")[0]
            user = User(
                user_id=user_id,
                email=email,
                first_name=local_part,
                last_name="",
                is_active=True,
                is_verified=True,
            )

            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Provisioned user profile from token: {user_id}")
            return user, None
        except Exception as e:
            db.rollback()
            logger.error(f"Error provisioning user from token: {str(e)}", exc_info=True)
            return None, "Unable to sync user profile"
    
    @staticmethod
    def update_user_profile(user_id: str, profile_data: dict, db: Session) -> Tuple[Optional[User], Optional[str]]:
        """
        Update user profile
        
        Args:
            user_id: User ID
            profile_data: Dictionary with profile updates (first_name, last_name, profile_data, etc.)
            db: Database session
        
        Returns:
            Tuple of (Updated User object or None, error message or None)
        """
        try:
            user = db.query(User).filter_by(user_id=user_id).first()
            if not user:
                return None, "User not found"
            
            # Update allowed fields
            if 'first_name' in profile_data:
                user.first_name = profile_data['first_name']
            if 'last_name' in profile_data:
                user.last_name = profile_data['last_name']
            if 'profile_data' in profile_data:
                user.profile_data = profile_data['profile_data']
            
            db.commit()
            db.refresh(user)
            
            logger.info(f"User profile updated: {user_id}")
            return user, None
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating user profile: {str(e)}", exc_info=True)
            return None, f"Profile update failed: {str(e)}"
    
