"""Tax calculation and rule query routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.schemas import TaxCalculationRequest
from models.database import TaxRules, get_db
from services.tax_calculator import TaxCalculator

router = APIRouter(tags=["calculations"])


@router.post("/api/calculate-tax")
async def calculate_tax(request: TaxCalculationRequest):
    """Calculate tax liability for given income and regime."""
    try:
        if request.gross_income < 0:
            raise HTTPException(status_code=400, detail="Gross income cannot be negative")

        fiscal_year = request.fiscal_year or "2026-27"
        result = {}

        if request.regime in ["new", "both"]:
            result["new_regime"] = TaxCalculator.calculate_new_regime(request.gross_income, fiscal_year)
        if request.regime in ["old", "both"]:
            result["old_regime"] = TaxCalculator.calculate_old_regime(
                request.gross_income,
                request.deductions,
                fiscal_year,
            )
        if request.regime == "both":
            comparison = TaxCalculator.compare_regimes(request.gross_income, request.deductions, fiscal_year)
            result["comparison"] = comparison["comparison"]

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Tax calculation failed") from e


@router.post("/api/deduction-suggestions")
async def get_deduction_suggestions(
    gross_income: float,
    fiscal_year: Optional[str] = "2026-27",
    age: int = Query(30, ge=0, le=100),
):
    """Get suggested deductions based on income."""
    try:
        if gross_income < 0:
            raise HTTPException(status_code=400, detail="Gross income cannot be negative")

        return TaxCalculator.suggest_deductions(gross_income, fiscal_year or "2026-27", age)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get suggestions") from e


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
