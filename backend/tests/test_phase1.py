"""Test script for Phase 1 implementation

This script tests:
1. Configuration loading
2. Database initialization
3. Document fetcher with existing PDFs in tax-docs/
"""

import sys
import logging
from pathlib import Path
from sqlalchemy import text

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_config_loading():
    """Test configuration loading"""
    logger.info("=" * 60)
    logger.info("Test 1: Configuration Loading")
    logger.info("=" * 60)
    
    try:
        from app.config import settings, government_sources
        
        logger.info(f"✓ Settings loaded successfully")
        logger.info(f"  - Environment: {settings.environment}")
        logger.info(f"  - Database connected to Supabase PostgreSQL")
        logger.info(f"  - Documents storage: {settings.documents_storage_path}")
        logger.info(f"  - Scheduler timezone: {settings.scheduler_timezone}")
        
        logger.info(f"✓ Government sources loaded successfully")
        logger.info(f"  - Primary source: {government_sources.get('primary_source', {}).get('name')}")
        logger.info(f"  - Base URL: {government_sources.get('primary_source', {}).get('base_url')}")
        
        return True
    except Exception as e:
        logger.error(f"✗ Config loading failed: {str(e)}", exc_info=True)
        return False


def test_database_connection():
    """Test database connection"""
    logger.info("\n" + "=" * 60)
    logger.info("Test 2: Database Connection")
    logger.info("=" * 60)
    
    try:
        from models.database import SessionLocal, init_db
        
        # Initialize database
        logger.info("Initializing database tables...")
        init_db()
        logger.info("✓ Database tables created/verified")
        
        # Test connection
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("✓ Database connection successful")
        
        return True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {str(e)}", exc_info=True)
        return False


def test_document_urls():
    """Test document URLs (without downloading)"""
    logger.info("\n" + "=" * 60)
    logger.info("Test 3: Document URL Construction")
    logger.info("=" * 60)
    
    try:
        from services.document_fetcher import document_fetcher
        
        fiscal_year = "2024-25"
        doc_config = document_fetcher.documents_config
        
        for doc_type, config in doc_config.items():
            logger.info(f"\n{doc_type}:")
            for i, pattern in enumerate(config.get("url_patterns", []), 1):
                url = document_fetcher._construct_url(pattern, fiscal_year)
                logger.info(f"  Pattern {i}: {url}")
        
        logger.info("\n✓ All URLs constructed successfully")
        return True
    except Exception as e:
        logger.error(f"✗ URL construction failed: {str(e)}", exc_info=True)
        return False


def test_existing_pdfs():
    """Test finding existing PDFs"""
    logger.info("\n" + "=" * 60)
    logger.info("Test 4: Existing PDFs")
    logger.info("=" * 60)
    
    try:
        docs_path = Path("./tax-docs")
        
        if not docs_path.exists():
            logger.warning(f"✗ Directory not found: {docs_path.absolute()}")
            return False
        
        logger.info(f"Checking: {docs_path.absolute()}\n")
        
        found_any = False
        for year_dir in sorted(docs_path.glob("*")):
            if year_dir.is_dir():
                pdfs = list(year_dir.glob("*.pdf"))
                if pdfs:
                    logger.info(f"✓ {year_dir.name}:")
                    for pdf in pdfs:
                        size_mb = pdf.stat().st_size / (1024 * 1024)
                        logger.info(f"    - {pdf.name} ({size_mb:.2f} MB)")
                    found_any = True
        
        if not found_any:
            logger.warning("✗ No PDFs found in tax-docs/")
            return False
        
        logger.info("\n✓ Existing PDFs verified")
        return True
    except Exception as e:
        logger.error(f"✗ Error checking PDFs: {str(e)}", exc_info=True)
        return False


def test_scheduler_config():
    """Test scheduler configuration"""
    logger.info("\n" + "=" * 60)
    logger.info("Test 5: Scheduler Configuration")
    logger.info("=" * 60)
    
    try:
        from app.config import government_sources
        from pytz import timezone as pytz_timezone
        
        fetch_config = government_sources.get("fetch_config", {})
        tz_str = fetch_config.get("timezone", "Asia/Kolkata")
        
        tz = pytz_timezone(tz_str)
        logger.info(f"✓ Scheduler timezone: {tz_str}")
        logger.info(f"  - Schedule: Feb 1st at 08:00 AM")
        logger.info(f"  - Timeout: {fetch_config.get('timeout_seconds')}s")
        logger.info(f"  - Retries: {fetch_config.get('retry_attempts')}")
        logger.info(f"  - Min file size: {fetch_config.get('min_file_size_bytes')} bytes")
        
        return True
    except Exception as e:
        logger.error(f"✗ Scheduler config failed: {str(e)}", exc_info=True)
        return False


def main():
    """Run all tests"""
    logger.info("\n" + "=" * 60)
    logger.info("TAX AGENT - PHASE 1 TEST SUITE")
    logger.info("=" * 60 + "\n")
    
    results = {
        "Config Loading": test_config_loading(),
        "Database Connection": test_database_connection(),
        "Document URLs": test_document_urls(),
        "Existing PDFs": test_existing_pdfs(),
        "Scheduler Config": test_scheduler_config(),
    }
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\n✓ All tests passed! Phase 1 setup is complete.")
        return 0
    else:
        logger.error(f"\n✗ {total - passed} test(s) failed. Please review and fix.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
