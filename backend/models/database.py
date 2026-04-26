"""Database Models using SQLAlchemy"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, DECIMAL, Text, JSON, Boolean, TIMESTAMP, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.config import settings

# Database setup (Supabase PostgreSQL)
DATABASE_URL = settings.database_url
if not DATABASE_URL:
    raise ValueError("DATABASE_URL must be set (Supabase PostgreSQL connection string)")

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class TaxRules(Base):
    """Tax rules extracted from government documents"""
    __tablename__ = "tax_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(String(100), unique=True, index=True)
    description = Column(Text)
    regime = Column(String(20), index=True)  # 'old', 'new', 'both'
    fiscal_year = Column(String(10), index=True)  # '2025-26'
    category = Column(String(50), index=True)  # 'deduction', 'exemption', 'rate', 'surcharge', 'rebate'
    amount = Column(DECIMAL(15, 2), nullable=True)
    percentage = Column(DECIMAL(5, 2), nullable=True)
    source_document = Column(String(50))  # 'Finance_Bill', 'Memorandum', 'Budget_Highlights'
    extraction_date = Column(DateTime, default=datetime.utcnow)
    confidence_score = Column(DECIMAL(3, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_fiscal_regime', 'fiscal_year', 'regime'),
        Index('idx_category_regime', 'category', 'regime'),
    )


class UserCalculations(Base):
    """User tax calculations and history"""
    __tablename__ = "user_calculations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), index=True)  # External user ID
    uploaded_document_ids = Column(JSON)  # Array of doc IDs
    extracted_data = Column(JSON)  # Parsed salary data
    tax_old_regime = Column(DECIMAL(15, 2), nullable=True)
    tax_new_regime = Column(DECIMAL(15, 2), nullable=True)
    recommended_regime = Column(String(10), nullable=True)
    calculation_breakdown = Column(JSON)  # Detailed calculation breakdown
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
    )


class DocumentUpload(Base):
    """Document uploads for processing"""
    __tablename__ = "document_uploads"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(String(100), unique=True, index=True)
    user_id = Column(String(100), index=True)
    filename = Column(String(255))
    document_type = Column(String(50))  # 'form_16', 'salary_slip'
    file_path = Column(String(500))
    extraction_status = Column(String(20), default="pending")  # 'pending', 'success', 'failed'
    extracted_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_user_status', 'user_id', 'extraction_status'),
    )


class Form16Extraction(Base):
    """Structured extraction snapshots for uploaded Form-16/salary documents."""
    __tablename__ = "form16_extractions"

    id = Column(Integer, primary_key=True, index=True)
    extraction_id = Column(String(100), unique=True, index=True)
    upload_id = Column(String(100), index=True)
    user_id = Column(String(100), index=True)
    filename = Column(String(255), nullable=True)
    document_type = Column(String(50), nullable=True)
    classified_document_type = Column(String(50), nullable=True)
    storage_path = Column(String(500), nullable=True)
    sanitized_text_preview = Column(Text, nullable=True)
    extraction_method = Column(String(100), nullable=True)

    gross_salary = Column(DECIMAL(15, 2), nullable=True)
    salary_section_17_1 = Column(DECIMAL(15, 2), nullable=True)
    perquisites_17_2 = Column(DECIMAL(15, 2), nullable=True)
    profits_in_lieu_17_3 = Column(DECIMAL(15, 2), nullable=True)
    basic_salary = Column(DECIMAL(15, 2), nullable=True)
    hra = Column(DECIMAL(15, 2), nullable=True)
    lta = Column(DECIMAL(15, 2), nullable=True)
    travel_concession_exemption = Column(DECIMAL(15, 2), nullable=True)
    gratuity_exemption = Column(DECIMAL(15, 2), nullable=True)
    commuted_pension_exemption = Column(DECIMAL(15, 2), nullable=True)
    leave_encashment_exemption = Column(DECIMAL(15, 2), nullable=True)
    other_section10_exemptions = Column(DECIMAL(15, 2), nullable=True)
    total_section10_exemptions = Column(DECIMAL(15, 2), nullable=True)
    salary_after_section10_exemptions = Column(DECIMAL(15, 2), nullable=True)
    other_allowances = Column(DECIMAL(15, 2), nullable=True)
    deductions_80c = Column(DECIMAL(15, 2), nullable=True)
    deductions_80ccc = Column(DECIMAL(15, 2), nullable=True)
    deductions_80ccd_1 = Column(DECIMAL(15, 2), nullable=True)
    deductions_80ccd_1b = Column(DECIMAL(15, 2), nullable=True)
    deductions_80ccd_2 = Column(DECIMAL(15, 2), nullable=True)
    deductions_80d = Column(DECIMAL(15, 2), nullable=True)
    deductions_80e = Column(DECIMAL(15, 2), nullable=True)
    deductions_other = Column(DECIMAL(15, 2), nullable=True)
    entertainment_allowance = Column(DECIMAL(15, 2), nullable=True)
    standard_deduction = Column(DECIMAL(15, 2), nullable=True)
    professional_tax = Column(DECIMAL(15, 2), nullable=True)
    total_section16_deductions = Column(DECIMAL(15, 2), nullable=True)
    income_under_salary = Column(DECIMAL(15, 2), nullable=True)
    house_property_income = Column(DECIMAL(15, 2), nullable=True)
    other_sources_income = Column(DECIMAL(15, 2), nullable=True)
    total_other_income = Column(DECIMAL(15, 2), nullable=True)
    gross_total_income = Column(DECIMAL(15, 2), nullable=True)
    chapter_via_total_deductions = Column(DECIMAL(15, 2), nullable=True)
    tds = Column(DECIMAL(15, 2), nullable=True)
    net_salary = Column(DECIMAL(15, 2), nullable=True)
    taxable_income = Column(DECIMAL(15, 2), nullable=True)
    tax_payable = Column(DECIMAL(15, 2), nullable=True)
    net_payable_tax = Column(DECIMAL(15, 2), nullable=True)
    surcharge = Column(DECIMAL(15, 2), nullable=True)
    health_education_cess = Column(DECIMAL(15, 2), nullable=True)
    relief_89 = Column(DECIMAL(15, 2), nullable=True)
    section_87a_rebate = Column(DECIMAL(15, 2), nullable=True)
    house_rent_exemption_10_13a = Column(DECIMAL(15, 2), nullable=True)
    donations_80g = Column(DECIMAL(15, 2), nullable=True)
    other_income = Column(DECIMAL(15, 2), nullable=True)

    financial_year = Column(String(15), nullable=True)
    assessment_year = Column(String(15), nullable=True)
    form16_part_a_present = Column(Boolean, nullable=True)
    form16_part_b_present = Column(Boolean, nullable=True)

    employee_name = Column(String(255), nullable=True)
    employer_name = Column(String(255), nullable=True)
    pan = Column(String(20), nullable=True)
    pan_last4 = Column(String(4), nullable=True)
    address = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_form16_user_created', 'user_id', 'created_at'),
        Index('idx_form16_upload', 'upload_id'),
    )


class RuleCache(Base):
    """Metadata for rule extraction and caching"""
    __tablename__ = "rule_cache"

    id = Column(Integer, primary_key=True, index=True)
    fiscal_year = Column(String(10), unique=True, index=True)
    last_extraction_date = Column(DateTime, nullable=True)
    total_rules_extracted = Column(Integer, default=0)
    extraction_status = Column(String(20))  # 'success', 'partial', 'failed'
    error_message = Column(Text, nullable=True)
    documents_fetched = Column(JSON)  # {'memo': True, 'finance_bill': True, 'budget_highlights': False}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentFetchLog(Base):
    """Logs for document fetching operations"""
    __tablename__ = "document_fetch_logs"

    id = Column(Integer, primary_key=True, index=True)
    fiscal_year = Column(String(10), index=True)
    document_type = Column(String(50))  # 'memo', 'finance_bill', 'budget_highlights'
    url = Column(String(500))
    status = Column(String(20))  # 'success', 'failed'
    file_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    fetch_time_seconds = Column(DECIMAL(5, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_fiscal_type', 'fiscal_year', 'document_type'),
    )


class User(Base):
    """User account model for authentication"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), unique=True, index=True)  # UUID
    email = Column(String(255), unique=True, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    profile_data = Column(JSON, nullable=True)  # Additional profile info
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_created', 'created_at'),
    )


class ChatSession(Base):
    """Chat session for agent interactions"""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(50), unique=True, index=True)  # UUID
    user_id = Column(String(50), index=True)  # Foreign key to User
    agent_type = Column(String(50))  # 'tax', 'investment', 'security'
    messages_count = Column(Integer, default=0)
    preview = Column(String(255), nullable=True)  # First message preview
    last_message_at = Column(DateTime, nullable=True)
    session_data = Column(JSON, nullable=True)  # Session context
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_session_user', 'user_id', 'created_at'),
    )


class ChatMessage(Base):
    """Individual messages in a chat session"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(50), index=True)  # Foreign key to ChatSession
    role = Column(String(20))  # 'user', 'assistant'
    content = Column(Text)
    message_metadata = Column(JSON, nullable=True)  # Additional context
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_message_session', 'session_id', 'created_at'),
    )


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables with cleanup of orphaned indexes"""
    try:
        # Clean up orphaned indexes for users table
        with engine.connect() as conn:
            try:
                conn.execute(text("DROP INDEX IF EXISTS idx_user_email CASCADE"))
                conn.execute(text("DROP INDEX IF EXISTS idx_user_created CASCADE"))
                conn.commit()
            except Exception:
                pass  # Ignore if indexes don't exist
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Warning during database initialization: {str(e)}")
        # Continue anyway - tables might already exist


if __name__ == "__main__":
    # Create all tables
    init_db()
    print("Database tables created successfully!")
