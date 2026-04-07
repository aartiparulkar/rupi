"""Document Fetcher Service - Downloads government documents from indiabudget.gov.in"""

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from app.config import government_sources, settings
from models.database import DocumentFetchLog, TaxRules

logger = logging.getLogger(__name__)


class DocumentFetcher:
    """Download budget PDFs and extract salaried tax rules using LLM."""

    def __init__(self):
        self.base_url = government_sources.get("primary_source", {}).get("base_url", "https://www.indiabudget.gov.in")
        self.documents_config = government_sources.get("primary_source", {}).get("documents", {})
        self.fetch_config = government_sources.get("fetch_config", {})
        self.timeout = self.fetch_config.get("timeout_seconds", 30)
        self.retries = self.fetch_config.get("retry_attempts", 3)
        self.min_file_size = self.fetch_config.get("min_file_size_bytes", 1048576)  # 1MB
        self.validate_pdf_magic = self.fetch_config.get("validate_pdf_magic", True)


    # Define the budget release date logic
    def get_budget_release_date(self, year: int) -> date:
        """Return budget release date: Feb 1, or next immediate working day for weekends."""
        release_date = date(year, 2, 1)
        while release_date.weekday() >= 5:
            release_date += timedelta(days=1)
        return release_date


    def is_budget_release_day(self) -> bool:
        """Return True when today is this year's release day."""
        today = datetime.now().date()
        return today == self.get_budget_release_date(today.year)


    # Construct the current financial year string
    def get_current_budget_fiscal_year(self) -> str:
        """Map current budget year to fiscal label format: previous-current (e.g., 2026-27)."""
        today = datetime.now().date()
        budget_year = today.year
        if today < self.get_budget_release_date(today.year):
            budget_year -= 1

        start_year = budget_year - 1
        return f"{start_year}-{budget_year % 100:02d}"


    # download all 3 documents 
    def run_budget_pipeline(self, fiscal_year: str, db: Session) -> Dict[str, Dict]:
        """Run pipeline: download memo/finance bill/bh1 then extract salaried tax rules with LLM."""
        results: Dict[str, Dict] = {}
        downloaded_files: Dict[str, Path] = {}

        logger.info(f"Starting budget pipeline for fiscal year {fiscal_year}")

        for doc_type in ["memorandum", "finance_bill", "budget_highlights"]:
            doc_config = self.documents_config.get(doc_type, {})
            url_patterns = doc_config.get("url_patterns", [])

            success, saved_path = False, None
            if not url_patterns:
                logger.error(f"No URL patterns configured for {doc_type}")
            else:
                for pattern in url_patterns:
                    url = self._construct_url(pattern, fiscal_year)

                    for attempt in range(self.retries):
                        try:
                            logger.info(f"Fetching {doc_type} from {url} (attempt {attempt + 1}/{self.retries})")
                            success, saved_path = self._download_file(url, doc_type, fiscal_year, db)
                            if success:
                                break
                        except requests.exceptions.RequestException as e:
                            logger.warning(f"Request failed for {url}: {str(e)}")
                            if attempt < self.retries - 1:
                                wait_time = self.fetch_config.get("retry_backoff_seconds", 5) ** attempt
                                time.sleep(wait_time)
                        except Exception as e:
                            logger.error(f"Unexpected error downloading {doc_type}: {str(e)}")
                            break

                    if success:
                        break

                if not success:
                    logger.error(f"Failed to fetch {doc_type} from configured URL patterns")

            if success and saved_path:
                downloaded_files[doc_type] = saved_path

            results[doc_type] = {
                "downloaded": success,
                "file_path": str(saved_path) if saved_path else None,
            }

        extraction_results = self._extract_and_store_rules(downloaded_files, fiscal_year, db)
        results["rule_extraction"] = extraction_results
        results["generated_tax_slab_preview"] = self._build_tax_slab_preview(
            fiscal_year,
            extraction_results.get("all_rules", []),
        )

        return results


    def _construct_url(self, pattern: str, fiscal_year: str) -> str:
        url_path = pattern.replace("{fiscal_year}", fiscal_year)
        return f"{self.base_url}{url_path}"


    def _download_file(self, url: str, doc_type: str, fiscal_year: str, db: Session) -> Tuple[bool, Optional[Path]]:
        """Download and validate PDF, then save to tax-docs/<fiscal_year>/..."""
        start_time = datetime.now(datetime.timezone.utc)

        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                allow_redirects=True,
            )
            response.raise_for_status()

            # Validation: don't download if the file is too small
            file_size = len(response.content)
            if file_size < self.min_file_size:
                self._log_fetch(url, doc_type, fiscal_year, "failed", file_size, error="File too small", start_time=start_time, db=db)
                return False, None
            
            
            # Optional: validate PDF magic number
            if self.validate_pdf_magic and not response.content.startswith(b"%PDF"):
                self._log_fetch(url, doc_type, fiscal_year, "failed", file_size, error="Invalid PDF format", start_time=start_time, db=db)
                return False, None

            save_path = self._get_save_path(doc_type, fiscal_year)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.content)

            self._log_fetch(url, doc_type, fiscal_year, "success", file_size, start_time=start_time, db=db)
            return True, save_path
        except requests.exceptions.HTTPError as e:
            status_code = getattr(getattr(e, "response", None), "status_code", 0)
            if status_code == 404:
                self._log_fetch(url, doc_type, fiscal_year, "failed", 0, error="URL not found (404)", start_time=start_time, db=db)
            else:
                self._log_fetch(url, doc_type, fiscal_year, "failed", 0, error=f"HTTP {status_code}", start_time=start_time, db=db)
            return False, None
        except requests.exceptions.Timeout:
            self._log_fetch(url, doc_type, fiscal_year, "failed", 0, error="Request timeout", start_time=start_time, db=db)
            return False, None
        except Exception as e:
            self._log_fetch(url, doc_type, fiscal_year, "failed", 0, error=str(e), start_time=start_time, db=db)
            return False, None


    def _extract_and_store_rules(self, downloaded_files: Dict[str, Path], fiscal_year: str, db: Session) -> Dict[str, Dict]:
        """Extract tax rules relevant to salaried individuals using LLM and store in DB."""
        from services.llm_extractor import llm_extractor
        from services.pdf_processor import pdf_processor

        if not downloaded_files:
            return {"status": "skipped", "reason": "No files downloaded"}

        extraction_results: Dict[str, Dict] = {}
        all_extracted_rules = []

        for doc_type, pdf_file in downloaded_files.items():
            try:
                if not pdf_processor.validate_pdf(str(pdf_file)):
                    extraction_results[doc_type] = {"status": "failed", "reason": "Invalid PDF"}
                    continue

                text = pdf_processor.extract_text(str(pdf_file), use_llm_cleanup=True)
                if not text.strip():
                    extraction_results[doc_type] = {"status": "failed", "reason": "No text extracted"}
                    continue

                rules, confidence = llm_extractor.extract_rules(text, fiscal_year, doc_type)
                all_extracted_rules.extend(rules)
                rules_stored = 0

                for rule in rules:
                    rule_id = rule.get("rule_id")
                    if not rule_id:
                        continue

                    if db.query(TaxRules).filter_by(rule_id=rule_id).first():
                        continue

                    db.add(
                        TaxRules(
                            rule_id=rule_id,
                            description=rule.get("description"),
                            regime=rule.get("regime"),
                            fiscal_year=fiscal_year,
                            category=rule.get("category"),
                            amount=rule.get("amount"),
                            percentage=rule.get("percentage"),
                            source_document=pdf_file.name,
                            extraction_date=datetime.now(datetime.timezone.utc),
                            confidence_score=rule.get("confidence_score", 0.75),
                        )
                    )
                    rules_stored += 1

                db.commit()
                extraction_results[doc_type] = {
                    "status": "success",
                    "rules_extracted": len(rules),
                    "rules_stored": rules_stored,
                    "extraction_confidence": float(confidence),
                }
            except Exception as e:
                db.rollback()
                extraction_results[doc_type] = {"status": "failed", "reason": str(e)}

        extraction_results["all_rules"] = all_extracted_rules
        return extraction_results

    def _build_tax_slab_preview(self, fiscal_year: str, extracted_rules: list) -> Dict:
        """Build a tax_slabs.json-like preview from LLM output without writing to tax_slabs.json."""
        old_slabs = []
        new_slabs = []
        deductions = {}

        for rule in extracted_rules:
            category = str(rule.get("category", "")).lower()
            regime = str(rule.get("regime", "")).lower()
            description = rule.get("description")

            if "tax" in category and "rate" in category:
                slab = {
                    "min": None,
                    "max": None,
                    "rate": rule.get("percentage"),
                    "description": description,
                }
                if "old" in regime or "both" in regime:
                    old_slabs.append(slab)
                if "new" in regime or "both" in regime:
                    new_slabs.append(slab)

            if "deduction" in category:
                key = (rule.get("rule_id") or "deduction").lower()
                deductions[key] = {
                    "name": description,
                    "max_amount": rule.get("amount"),
                }

        return {
            "fiscal_years": {
                fiscal_year: {
                    "health_cess_rate": 0.04,
                    "regimes": {
                        "old_regime": {
                            "slabs": old_slabs,
                            "allowable_deductions": deductions,
                        },
                        "new_regime": {
                            "slabs": new_slabs,
                        },
                    },
                }
            },
        }

    def _get_save_path(self, doc_type: str, fiscal_year: str) -> Path:
        doc_mapping = {
            "memorandum": "memo.pdf",
            "finance_bill": "Finance_Bill.pdf",
            "budget_highlights": "bh1.pdf",
        }
        filename = doc_mapping.get(doc_type, f"{doc_type}.pdf")
        timestamp = datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        stem, ext = filename.rsplit(".", 1)
        filename_with_timestamp = f"{stem}_{timestamp}.{ext}"
        return Path(settings.documents_storage_path) / fiscal_year / filename_with_timestamp

    def _log_fetch(
        self,
        url: str,
        doc_type: str,
        fiscal_year: str,
        status: str,
        file_size: int,
        error: Optional[str] = None,
        start_time: Optional[datetime] = None,
        db: Optional[Session] = None,
    ) -> None:
        if db is None:
            return

        try:
            fetch_time_seconds = None
            if start_time:
                fetch_time_seconds = (datetime.now(datetime.timezone.utc) - start_time).total_seconds()

            db.add(
                DocumentFetchLog(
                    fiscal_year=fiscal_year,
                    document_type=doc_type,
                    url=url,
                    status=status,
                    file_size=file_size if file_size > 0 else None,
                    error_message=error,
                    fetch_time_seconds=fetch_time_seconds,
                )
            )
            db.commit()
        except Exception as e:
            logger.error(f"Error logging fetch: {str(e)}")

document_fetcher = DocumentFetcher()
