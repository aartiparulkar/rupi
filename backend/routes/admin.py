"""Admin routes."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import validate_fiscal_year
from models.database import (
    DocumentFetchLog,
    DocumentUpload,
    RuleCache,
    TaxRules,
    UserCalculations,
    get_db,
)
from services.document_fetcher import document_fetcher
from services.llm_extractor import llm_extractor
from services.pdf_processor import pdf_processor

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/fetch-documents")
async def admin_fetch_documents(fiscal_year: str = None, db: Session = Depends(get_db)):
    """Manually trigger budget pipeline."""
    try:
        if not fiscal_year:
            fiscal_year = document_fetcher.get_current_budget_fiscal_year()
        elif not validate_fiscal_year(fiscal_year):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid fiscal year format: '{fiscal_year}'. "
                    "Expected format: 'YYYY-YY' (e.g., '2024-25', '2025-26')"
                ),
            )

        results = document_fetcher.run_budget_pipeline(fiscal_year, db)
        return {"status": "success", "fiscal_year": fiscal_year, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/database-status")
async def database_status(db: Session = Depends(get_db)):
    """Check database connection and table row counts."""
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "connected",
            "tables": {
                "tax_rules": db.query(TaxRules).count(),
                "user_calculations": db.query(UserCalculations).count(),
                "document_uploads": db.query(DocumentUpload).count(),
                "rule_cache": db.query(RuleCache).count(),
                "document_fetch_logs": db.query(DocumentFetchLog).count(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/extract-rules")
async def admin_extract_rules(
    fiscal_year: str = None,
    document_type: str = None,
    db: Session = Depends(get_db),
):
    """Extract tax rules from downloaded fiscal-year PDFs."""
    try:
        if not fiscal_year:
            fiscal_year = document_fetcher.get_current_budget_fiscal_year()
        elif not validate_fiscal_year(fiscal_year):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid fiscal year format: '{fiscal_year}'. Expected format: 'YYYY-YY'",
            )

        docs_path = Path(settings.documents_storage_path) / fiscal_year
        if not docs_path.exists():
            raise HTTPException(status_code=404, detail=f"No documents found for fiscal year {fiscal_year}")

        if document_type:
            pdf_files = list(docs_path.glob(f"{document_type}*.pdf"))
            if not pdf_files:
                raise HTTPException(
                    status_code=404,
                    detail=f"No {document_type} documents found for {fiscal_year}",
                )
        else:
            pdf_files = list(docs_path.glob("*.pdf"))

        extraction_results = {}
        for pdf_file in pdf_files:
            if "memo" in pdf_file.name.lower():
                doc_type_key = "memorandum"
            elif "finance_bill" in pdf_file.name.lower():
                doc_type_key = "finance_bill"
            elif "bh1" in pdf_file.name.lower():
                doc_type_key = "budget_highlights"
            else:
                doc_type_key = "other"

            try:
                if not pdf_processor.validate_pdf(str(pdf_file)):
                    extraction_results[doc_type_key] = {"status": "failed", "reason": "Invalid PDF"}
                    continue

                text = pdf_processor.extract_text(str(pdf_file), use_llm_cleanup=True)
                if not text.strip():
                    extraction_results[doc_type_key] = {"status": "failed", "reason": "No text extracted"}
                    continue

                rules, confidence = llm_extractor.extract_rules(text, fiscal_year, doc_type_key)
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
                            extraction_date=datetime.utcnow(),
                            confidence_score=rule.get("confidence_score", 0.75),
                        )
                    )
                    rules_stored += 1

                db.commit()
                extraction_results[doc_type_key] = {
                    "status": "success",
                    "rules_extracted": len(rules),
                    "rules_stored": rules_stored,
                    "extraction_confidence": float(confidence),
                }
            except Exception as e:
                db.rollback()
                extraction_results[doc_type_key] = {"status": "failed", "reason": str(e)}

        return {
            "status": "success",
            "fiscal_year": fiscal_year,
            "documents_processed": len(pdf_files),
            "results": extraction_results,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
