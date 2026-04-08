"""Application Configuration"""

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import json
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Database (Supabase PostgreSQL)
    database_url: str
    
    # Supabase
    supabase_url: Optional[str] = None
    service_role_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )  # Use the service_role key for backend operations
    supabase_jwt_secret: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_JWT_SECRET", "JWT_SECRET"),
    )
    supabase_bucket: str = Field(
        default="rupi-documents",
        validation_alias=AliasChoices("SUPABASE_BUCKET", "SUPABASE_BUCKET_NAME"),
    )
    
    # API Keys
    anthropic_api_key: Optional[str] = None
    openai_api_key: str
    gemini_api_key: Optional[str] = None
    
    # Application
    log_level: str = "INFO"
    debug: bool = False
    environment: str = "development"
    
    # Document Fetching
    document_fetch_timeout: int = 30
    document_fetch_retries: int = 3
    
    # File Storage
    documents_storage_path: str = "./tax-docs"
    temp_upload_path: str = "./temp_uploads"
    
    # OCR Configuration
    tesseract_path: Optional[str] = None
    
    # Scheduler
    scheduler_timezone: str = "Asia/Kolkata"
    
    # JWT Authentication
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    model_config = SettingsConfigDict(
        env_file=(
            str(Path(__file__).resolve().parents[2] / ".env"),
            str(Path(__file__).resolve().parents[1] / ".env"),
        ),
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("debug", mode="before")
    @classmethod
    def _coerce_debug(cls, value):
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False
        return False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create storage directories if they don't exist
        Path(self.documents_storage_path).mkdir(parents=True, exist_ok=True)
        Path(self.temp_upload_path).mkdir(parents=True, exist_ok=True)


# Load government sources configuration
def load_government_sources():
    """Load government document sources from config file"""
    config_path = Path(__file__).parent.parent / "config" / "government_sources.json"
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}


# Initialize settings
settings = Settings()
government_sources = load_government_sources()
