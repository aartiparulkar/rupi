"""APScheduler Configuration for automated document fetching"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from pytz import timezone as pytz_timezone
from services.document_fetcher import document_fetcher
from models.database import SessionLocal
from app.config import settings, government_sources

logger = logging.getLogger(__name__)

# Create scheduler
scheduler = BackgroundScheduler()


def fetch_documents_job():
    """Job to fetch and extract budget documents on release working day."""
    try:
        if not document_fetcher.is_budget_release_day():
            logger.info("Skipping fetch job: today is not the budget release working day")
            return

        current_fiscal_year = document_fetcher.get_current_budget_fiscal_year()
        
        logger.info(f"Starting scheduled document fetch for fiscal year {current_fiscal_year}")
        
        db = SessionLocal()
        try:
            results = document_fetcher.run_budget_pipeline(current_fiscal_year, db)
            logger.info(f"Document fetch completed. Results: {results}")
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error in scheduled document fetch job: {str(e)}", exc_info=True)


def start_scheduler():
    """Start the background scheduler"""
    if scheduler.running:
        logger.warning("Scheduler is already running")
        return
    
    try:
        fetch_config = government_sources.get("fetch_config", {})
        timezone_str = fetch_config.get("timezone", "Asia/Kolkata")
        tz = pytz_timezone(timezone_str)
        
        # Schedule checks for Feb 1-3, then execute only on computed release working day.
        scheduler.add_job(
            fetch_documents_job,
            trigger=CronTrigger(month=2, day="1-3", hour=8, minute=0, timezone=tz),
            id="fetch_documents_job",
            name="Fetch Government Documents",
            misfire_grace_time=3600,  # 1 hour grace period
            replace_existing=True
        )
        
        scheduler.start()
        logger.info(f"Scheduler started. Document fetch checks scheduled for Feb 1-3 at 08:00 AM {timezone_str}")
        
    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}", exc_info=True)


def stop_scheduler():
    """Stop the background scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


def trigger_fetch_manually(fiscal_year: str = None):
    """Manually trigger document fetch (for testing)"""
    try:
        if not fiscal_year:
            fiscal_year = document_fetcher.get_current_budget_fiscal_year()
        
        logger.info(f"Manually triggering document fetch for fiscal year {fiscal_year}")
        
        db = SessionLocal()
        try:
            results = document_fetcher.run_budget_pipeline(fiscal_year, db)
            logger.info(f"Manual document fetch completed. Results: {results}")
            return results
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error in manual document fetch: {str(e)}", exc_info=True)
        raise
