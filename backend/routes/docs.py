"""Document utility routes migrated from Node backend."""

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_from_header
from models.database import User

router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.get("/verify/{hash_value}")
async def verify_document_hash(
    hash_value: str,
    current_user: User = Depends(get_current_user_from_header),
):
    """Placeholder hash verification endpoint."""
    return {
        "hash": hash_value,
        "verified": True,
        "message": "Blockchain verification endpoint (integrate IPFS here)",
        "user": current_user.user_id,
    }
