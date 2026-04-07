"""Shared FastAPI dependencies and validators."""

import re
from datetime import datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from models.database import User, get_db
from services.auth_service import AuthService
from services.auth_utils import AuthUtils


async def get_current_user_from_header(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Get current user from JWT token in Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = parts[1]
    payload = AuthUtils.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("user_id") or payload.get("sub") or payload.get("id")
    user_email = payload.get("email")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user identity")

    user, user_error = AuthService.get_or_create_user_from_token(user_id, user_email, db)
    if user_error:
        raise HTTPException(status_code=401, detail=user_error)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def validate_fiscal_year(fiscal_year: str) -> bool:
    """Validate fiscal year format and keep range to recent years."""
    if not fiscal_year:
        return False

    match = re.match(r"^(\d{4})-(\d{2})$", fiscal_year)
    if not match:
        return False

    year_start = int(match.group(1))
    year_end = int(match.group(2))
    expected_year_end = (year_start + 1) % 100
    if year_end != expected_year_end:
        return False

    current_date = datetime.now()
    current_fiscal_start = current_date.year if current_date.month >= 2 else current_date.year - 1
    min_year = current_fiscal_start - 3
    max_year = current_fiscal_start

    return min_year <= year_start <= max_year
