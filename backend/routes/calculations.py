"""Tax calculation and rule query routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.schemas import TaxCalculationRequest, TaxCalculationFromExtractionRequest, ValidateExtractionRequest
from app.dependencies import get_current_user_from_header
from models.database import TaxRules, Form16Extraction, get_db, User
from services.tax_calculator import TaxCalculator

router = APIRouter(tags=["calculations"])


def _calculate_tax_from_extraction_request(
    request: TaxCalculationFromExtractionRequest,
    current_user: User,
    db: Session,
):
    """Shared extraction-based tax calculation implementation."""
    if request.extraction_id:
        form16_data = db.query(Form16Extraction).filter(
            Form16Extraction.extraction_id == request.extraction_id,
            Form16Extraction.user_id == current_user.id,
        ).first()
    else:
        form16_data = db.query(Form16Extraction).filter(
            Form16Extraction.user_id == current_user.id,
        ).order_by(Form16Extraction.created_at.desc()).first()

    if not form16_data:
        raise HTTPException(
            status_code=404,
            detail="No extraction found. Please upload a Form 16 document first.",
        )

    regime = request.regime or "both"
    fiscal_year = request.fiscal_year or getattr(form16_data, "financial_year", None)
    deductions = 0
    if regime in ["old", "both"]:
        deduction_breakdown = {
            "section_80c": TaxCalculator._safe_float(form16_data.deductions_80c) or 0,
            "section_80d": TaxCalculator._safe_float(form16_data.deductions_80d) or 0,
            "section_80e": TaxCalculator._safe_float(form16_data.deductions_80e_ccd_1) or 0,
            "section_80ccc": TaxCalculator._safe_float(form16_data.deductions_80ccc) or 0,
            "section_80ccd_1": TaxCalculator._safe_float(form16_data.deductions_80ccd_1) or 0,
            "section_80ccd_1b": TaxCalculator._safe_float(form16_data.deductions_80ccd_1b) or 0,
            "section_80ccd_2": TaxCalculator._safe_float(form16_data.deductions_80ccd_2) or 0,
            "entertainment_allowance_16": TaxCalculator._safe_float(form16_data.entertainment_allowance_16) or 0,
            "professional_tax_16": TaxCalculator._safe_float(form16_data.professional_tax_16) or 0,
            "standard_deduction": TaxCalculator._safe_float(form16_data.standard_deduction) or 0,
            "donations_80g": TaxCalculator._safe_float(form16_data.donations_80g) or 0,
            "chapter_vi_a_total": TaxCalculator._safe_float(form16_data.chapter_via_total_deductions) or 0,
            "total_deductions_chapter_vi_a": TaxCalculator._safe_float(form16_data.chapter_via_total_deductions) or 0,
        }
        deductions = sum(deduction_breakdown.values())

    result = TaxCalculator.calculate_tax(
        form16_extraction=form16_data,
        fiscal_year=fiscal_year,
        regime=regime,
        deductions=deductions,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/api/calculate-tax")
async def calculate_tax_endpoint(
    request: Optional[TaxCalculationRequest] = None,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """
    Unified tax calculation endpoint.
    
    Priority:
    1. If extraction_id provided: use Form16Extraction from database
    2. If extraction_id not provided: use latest extraction for user
    3. If no extraction: use manual gross_income from request
    4. If no data: ask user for required fields in chat
    
    Supports both extraction-based and manual calculation.
    """
    try:
        form16_data = None
        
        # Try to get extraction data if available
        if hasattr(request, 'extraction_id') and request.extraction_id:
            form16_data = db.query(Form16Extraction).filter(
                Form16Extraction.extraction_id == request.extraction_id,
                Form16Extraction.user_id == current_user.id
            ).first()
        else:
            # Try to get latest extraction for user
            form16_data = db.query(Form16Extraction).filter(
                Form16Extraction.user_id == current_user.id
            ).order_by(Form16Extraction.created_at.desc()).first()
        
        # Prepare calculation parameters
        calc_kwargs = {
            "form16_extraction": form16_data,
            "fiscal_year": request.fiscal_year if request else None,
            "regime": request.regime if request else "both",
        }
        
        # Add manual input if provided and no extraction
        if request and request.gross_income and not form16_data:
            calc_kwargs["gross_income"] = request.gross_income
            calc_kwargs["deductions"] = request.deductions or 0
        
        result = TaxCalculator.calculate_tax(**calc_kwargs)
        
        if "error" in result:
            # If missing critical fields, this is expected - return with prompts
            if "missing_fields" in result:
                return {
                    "status": "incomplete",
                    "message": "Additional information needed",
                    "missing_fields": result.get("missing_fields"),
                    "user_prompts": result.get("user_prompts"),
                    "note": result.get("note"),
                }
            # Otherwise it's a real error
            raise HTTPException(status_code=400, detail=result["error"])
        
        return {
            "status": "success",
            "data": result,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Tax calculation failed: {str(e)}"
        ) from e


@router.post("/api/calculate-tax-with-extraction")
async def calculate_tax_from_extraction_endpoint(
    request: TaxCalculationFromExtractionRequest,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Compatibility alias for extraction-based tax calculation."""
    try:
        return _calculate_tax_from_extraction_request(request, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calculation failed: {str(e)}") from e


@router.get("/api/tax-rules")
async def get_tax_rules(
    fiscal_year: Optional[str] = None,
    regime: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Retrieve extracted tax rules with optional filters."""
    try:
        query = db.query(TaxRules)
        if fiscal_year:
            query = query.filter_by(fiscal_year=fiscal_year)
        if regime:
            query = query.filter(TaxRules.regime.contains(regime))
        if category:
            query = query.filter_by(category=category)

        rules = query.order_by(TaxRules.created_at.desc()).limit(100).all()
        return {
            "count": len(rules),
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "description": rule.description,
                    "regime": rule.regime,
                    "category": rule.category,
                    "fiscal_year": rule.fiscal_year,
                    "amount": float(rule.amount) if rule.amount else None,
                    "percentage": float(rule.percentage) if rule.percentage else None,
                    "source_document": rule.source_document,
                    "confidence_score": float(rule.confidence_score) if rule.confidence_score else None,
                }
                for rule in rules
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to retrieve tax rules") from e


@router.post("/api/calculate-tax-from-extraction")
async def calculate_tax_from_extraction(
    request: TaxCalculationFromExtractionRequest,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Canonical extraction-based tax calculation endpoint."""
    try:
        return _calculate_tax_from_extraction_request(request, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Tax calculation from extraction failed: {str(e)}"
        ) from e


@router.post("/api/validate-extraction")
async def validate_extraction(
    request: ValidateExtractionRequest,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Validate extracted tax values by calculating and comparing"""
    try:
        # Fetch extraction
        if request.extraction_id:
            form16_data = db.query(Form16Extraction).filter(
                Form16Extraction.extraction_id == request.extraction_id,
                Form16Extraction.user_id == current_user.id
            ).first()
        else:
            form16_data = db.query(Form16Extraction).filter(
                Form16Extraction.user_id == current_user.id
            ).order_by(Form16Extraction.created_at.desc()).first()
        
        if not form16_data:
            raise HTTPException(
                status_code=404,
                detail="No extraction found to validate"
            )
        
        result = TaxCalculator.validate_extracted_vs_calculated(
            form16_data,
            regime=request.regime or "old"
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Validation failed: {str(e)}"
        ) from e


@router.get("/api/user/tax-extractions")
async def get_tax_extractions(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Get user's Form16 extractions history"""
    try:
        total = db.query(Form16Extraction).filter_by(user_id=current_user.id).count()
        
        extractions = db.query(Form16Extraction).filter_by(
            user_id=current_user.id
        ).order_by(
            Form16Extraction.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        return {
            "total": total,
            "count": len(extractions),
            "offset": offset,
            "limit": limit,
            "extractions": [
                {
                    "extraction_id": e.extraction_id,
                    "filename": e.filename,
                    "document_type": e.classified_document_type,
                    "financial_year": e.financial_year,
                    "assessment_year": e.assessment_year,
                    "gross_salary": float(e.gross_salary) if e.gross_salary else None,
                    "taxable_income": float(e.taxable_income) if e.taxable_income else None,
                    "tax_payable": float(e.tax_payable) if e.tax_payable else None,
                    "tds_deducted": float(e.tds) if e.tds else None,
                    "extraction_method": e.extraction_method,
                    "created_at": e.created_at,
                    "part_a_present": e.form16_part_a_present,
                    "part_b_present": e.form16_part_b_present,
                }
                for e in extractions
            ],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve extractions"
        ) from e
