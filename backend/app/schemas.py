"""Pydantic request/response schemas for the API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

class UpdateProfileRequest(BaseModel):
    """Update user profile request"""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_data: Optional[dict] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    profession: Optional[str] = None
    pan: Optional[str] = None
    incomeRange: Optional[str] = None
    taxRegime: Optional[str] = None
    riskAppetite: Optional[str] = None
    goals: Optional[list] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    profileComplete: Optional[bool] = None
    mfaEnabled: Optional[bool] = None
    loginNotifications: Optional[bool] = None
    authProvider: Optional[str] = None


class CreateChatSessionRequest(BaseModel):
    """Create chat session request"""

    agent_type: Optional[str] = None  # 'tax', 'invest', or 'security'
    agent: Optional[str] = None  # Node-compatible alias
    initial_message: Optional[str] = None


class ChatMessageRequest(BaseModel):
    """Chat message request model"""

    role: str  # 'user' or 'assistant'
    content: str


class TaxCalculationRequest(BaseModel):
    """Tax calculation request"""

    gross_income: float
    regime: Optional[str] = "both"  # 'old', 'new', or 'both'
    deductions: Optional[float] = 0  # Only for old regime
    fiscal_year: Optional[str] = "2026-27"  # Format: "2024-25"


class DocumentResponse(BaseModel):
    """Document response model"""

    upload_id: str
    user_id: str
    filename: str
    document_type: str
    extraction_status: str
    created_at: datetime

    class Config:
        from_attributes = True