"""Tax calculation engine for Old and New tax regimes."""

import logging
from typing import Dict, Optional, List, Tuple
from decimal import Decimal
from services.tax_slab_loader import TaxSlabLoader

logger = logging.getLogger(__name__)


class TaxCalculator:
    """Pure tax calculation engine with loader-backed tax slab configuration."""
    
    DEFAULT_FISCAL_YEAR = "2026-27"
    CRITICAL_FIELDS = ["gross_total_income"]  # Field needed for basic calculation
    DEFAULT_HEALTH_CESS_RATE = 0.04

    @staticmethod
    def _get_rules(fiscal_year: Optional[str] = None, tax_rules: Optional[Dict] = None) -> Dict:
        """Load tax rules from TaxSlabLoader and optionally merge caller overrides."""
        loaded = TaxSlabLoader.load_slabs() or {}
        fiscal_year = fiscal_year or TaxCalculator.DEFAULT_FISCAL_YEAR
        fiscal_data = loaded.get("fiscal_years", {}).get(fiscal_year)

        if fiscal_data is None:
            fiscal_years = list(loaded.get("fiscal_years", {}).keys())
            if fiscal_years:
                fiscal_year = sorted(fiscal_years)[-1]
                fiscal_data = loaded["fiscal_years"][fiscal_year]

        if not fiscal_data:
            return tax_rules or {}

        rules = {
            "old_regime": dict(fiscal_data.get("regimes", {}).get("old_regime", {})),
            "new_regime": dict(fiscal_data.get("regimes", {}).get("new_regime", {})),
            "health_cess_rate": float(fiscal_data.get("health_cess_rate", TaxCalculator.DEFAULT_HEALTH_CESS_RATE)),
        }

        if tax_rules:
            for key, value in tax_rules.items():
                if key in rules and isinstance(rules[key], dict) and isinstance(value, dict):
                    merged = dict(rules[key])
                    merged.update(value)
                    rules[key] = merged
                else:
                    rules[key] = value

        return rules

    @staticmethod
    def _sum_fields(fields: Dict[str, Decimal], names: List[str]) -> Decimal:
        total = Decimal("0")
        for name in names:
            value = fields.get(name)
            if value is not None:
                total += Decimal(str(value))
        return total

    @staticmethod
    def _safe_decimal(value) -> Optional[Decimal]:
        """Safely convert value to Decimal, returning None if not possible"""
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (TypeError, ValueError):
            return None
    
    @staticmethod
    def calculate_tax(
        form16_extraction=None,
        gross_income: Optional[float] = None,
        deductions: Optional[float] = 0,
        fiscal_year: Optional[str] = None,
        regime: str = "both",
        **kwargs  # Additional optional deductions or manual overrides
    ) -> Dict:
        """Pure tax calculation using detailed fields for old/both and gross income for new regime."""
        try:
            tax_rules = TaxCalculator._get_rules(fiscal_year, kwargs.pop("tax_rules", None))
            if regime in ["old", "both"] and not tax_rules.get("old_regime"):
                return {"error": "Tax slab configuration unavailable for old regime"}
            if regime in ["new", "both"] and not tax_rules.get("new_regime"):
                return {"error": "Tax slab configuration unavailable for new regime"}
            available_fields = {}
            extraction_metadata = {}

            allowed_keys = {
                "gross_income",
                "gross_salary",
                "salary_section_17_1",
                "perquisites_17_2",
                "profits_in_lieu_17_3",
                "basic_salary",
                "other_allowances",
                "travel_concession_exemption",
                "gratuity_exemption",
                "commuted_pension_exemption",
                "leave_encashment_exemption",
                "other_section10_exemptions",
                "total_section10_exemptions",
                "salary_after_section10_exemptions",
                "house_rent_exemption_10_13a",
                "deductions_80c",
                "deductions_80ccc",
                "deductions_80ccd_1",
                "deductions_80ccd_1b",
                "deductions_80ccd_2",
                "deductions_80d",
                "deductions_80e",
                "deductions_80tta",
                "deductions_other",
                "entertainment_allowance",
                "standard_deduction",
                "professional_tax",
                "total_section16_deductions",
                "donations_80g",
                "income_under_salary",
                "house_property_income",
                "other_sources_income",
                "total_other_income",
                "other_income",
                "gross_total_income",
                "chapter_via_total_deductions",
                "taxable_income",
                "tax_payable",
                "net_payable_tax",
                "surcharge",
                "health_education_cess",
                "relief_89",
                "section_87a_rebate",
                "tds",
                "net_salary",
            }

            if form16_extraction is not None:
                if isinstance(form16_extraction, dict):
                    source_data = form16_extraction
                elif hasattr(form16_extraction, "__dict__"):
                    source_data = form16_extraction.__dict__
                else:
                    source_data = {}

                for key in allowed_keys:
                    value = TaxCalculator._safe_decimal(source_data.get(key))
                    if value is not None:
                        available_fields[key] = value

                extraction_metadata = {
                    "extraction_id": getattr(form16_extraction, "extraction_id", None),
                    "document_type": getattr(form16_extraction, "classified_document_type", None),
                    "financial_year": getattr(form16_extraction, "financial_year", None),
                }
                if not fiscal_year:
                    fiscal_year = extraction_metadata.get("financial_year")

            for key, value in kwargs.items():
                if key.startswith("deductions_") or key in allowed_keys:
                    available_fields[key] = TaxCalculator._safe_decimal(value)

            if deductions:
                available_fields["manual_deductions"] = TaxCalculator._safe_decimal(deductions)

            if not fiscal_year:
                fiscal_year = TaxCalculator.DEFAULT_FISCAL_YEAR

            gross_salary = available_fields.get("gross_salary")
            salary_components = TaxCalculator._sum_fields(
                available_fields,
                ["salary_section_17_1", "perquisites_17_2", "profits_in_lieu_17_3"],
            )

            if regime == "new":
                if gross_salary is None:
                    if gross_income is not None:
                        gross_salary = Decimal(str(gross_income))
                    elif available_fields.get("gross_total_income") is not None:
                        gross_salary = available_fields.get("gross_total_income")

                if gross_salary is None:
                    return {
                        "error": "gross_income is required for new regime calculation",
                        "missing_fields": ["gross_income"],
                        "available_fields": {k: float(v) for k, v in available_fields.items()},
                    }

                available_fields["gross_salary"] = gross_salary
            else:
                if gross_salary is None and salary_components > 0:
                    gross_salary = salary_components
                    available_fields["gross_salary"] = gross_salary

                if gross_salary is None and available_fields.get("gross_total_income") is not None:
                    gross_salary = available_fields.get("gross_total_income")

                if regime == "both" and gross_salary is None and gross_income is not None:
                    gross_salary = Decimal(str(gross_income))
                    available_fields["gross_salary"] = gross_salary

                if gross_salary is None:
                    missing_fields = [
                        "salary_section_17_1",
                        "perquisites_17_2",
                        "profits_in_lieu_17_3",
                    ]
                    return {
                        "error": "Insufficient data for old regime calculation",
                        "missing_fields": missing_fields,
                        "available_fields": {k: float(v) for k, v in available_fields.items()},
                    }

            if gross_salary is None:
                return {
                    "error": "Gross income is zero, cannot calculate tax",
                    "available_fields": {k: float(v) for k, v in available_fields.items()},
                }

            result = {
                "gross_income": float(gross_salary),
                "fiscal_year": fiscal_year,
                "regime": regime,
            }
            if extraction_metadata["extraction_id"]:
                result["extraction"] = extraction_metadata

            if regime in ["old", "both"]:
                result["old_regime"] = TaxCalculator._calculate_old_regime_tax(
                    available_fields=available_fields,
                    gross_income=float(gross_salary),
                    fiscal_year=fiscal_year,
                    rules=tax_rules.get("old_regime", {}),
                    health_cess_rate=tax_rules.get("health_cess_rate", TaxCalculator.DEFAULT_HEALTH_CESS_RATE),
                )
            
            if regime in ["new", "both"]:
                result["new_regime"] = TaxCalculator._calculate_new_regime_tax(
                    available_fields=available_fields,
                    gross_income=float(gross_salary),
                    fiscal_year=fiscal_year,
                    rules=tax_rules.get("new_regime", {}),
                    health_cess_rate=tax_rules.get("health_cess_rate", TaxCalculator.DEFAULT_HEALTH_CESS_RATE),
                )

            if regime == "both":
                old_tax = result["old_regime"]["net_payable_tax"]
                new_tax = result["new_regime"]["net_payable_tax"]
                savings = abs(old_tax - new_tax)
                recommended = "Old Regime" if old_tax < new_tax else "New Regime"
                
                result["comparison"] = {
                    "old_regime_tax": old_tax,
                    "new_regime_tax": new_tax,
                    "tax_difference": savings,
                    "recommended_regime": recommended,
                    "savings": savings,
                    "recommendation_reason": f"Choose {recommended} to save ₹{savings:,.2f}" if savings > 0 else "Both regimes result in similar tax liability",
                }

            result["available_fields_count"] = len(available_fields)
            result["income_breakdown"] = {
                k: float(available_fields[k])
                for k in [
                    "gross_salary",
                    "salary_section_17_1",
                    "income_under_salary",
                    "house_property_income",
                    "other_sources_income",
                    "gross_total_income",
                ]
                if k in available_fields
            }
            result["deduction_breakdown"] = {
                k: float(available_fields[k])
                for k in available_fields
                if k.startswith("deductions_") or "allowance" in k or k in {"professional_tax", "standard_deduction", "manual_deductions"}
            }
            result["tax_summary"] = {
                "gross_income": float(gross_salary),
                "total_deductions_used": float(result.get("old_regime", {}).get("chapter_via_total_deductions", 0) or 0),
                "taxable_income": float(result.get("old_regime", {}).get("taxable_income", 0) or 0),
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Tax calculation error: {e}")
            return {"error": f"Calculation failed: {str(e)}"}
    
    @staticmethod
    def _calculate_old_regime_tax(
        available_fields: Dict[str, Decimal],
        gross_income: float,
        fiscal_year: str,
        rules: Dict,
        health_cess_rate: float = 0.04,
    ) -> Dict:
        """Calculate tax for old regime with old-regime deductions."""
        standard_deduction_raw = rules.get("standard_deduction")
        if standard_deduction_raw is None:
            raise ValueError("Missing standard_deduction in tax_slabs.json for old_regime")
        standard_deduction = float(standard_deduction_raw)
        slabs = rules.get("slabs", [])
        rebate_config = (rules.get("rebate") or {}).get("section_87a", {})
        rebate_amount = float(rules.get("rebate_amount", rebate_config.get("amount", 0)) or 0)
        rebate_threshold = float(rules.get("rebate_threshold", rebate_config.get("threshold", 0)) or 0)

        section_10_allowance = TaxCalculator._sum_fields(
            available_fields,
            [
                "travel_concession_exemption",
                "gratuity_exemption",
                "commuted_pension_exemption",
                "leave_encashment_exemption",
                "other_section10_exemptions",
                "house_rent_exemption_10_13a",
            ],
        )
        salary_after_section10_exemptions = max(Decimal("0"), Decimal(str(gross_income)) - section_10_allowance)

        entertainment_allowance = TaxCalculator._safe_decimal(available_fields.get("entertainment_allowance")) or Decimal("0")
        professional_tax = TaxCalculator._safe_decimal(available_fields.get("professional_tax")) or Decimal("0")

        total_section16_deductions = Decimal(str(standard_deduction)) + entertainment_allowance + professional_tax

        income_under_salary = max(Decimal("0"), salary_after_section10_exemptions - total_section16_deductions)

        house_property_income = TaxCalculator._safe_decimal(available_fields.get("house_property_income")) or Decimal("0")
        other_sources_income = TaxCalculator._safe_decimal(available_fields.get("other_sources_income")) or Decimal("0")
        total_other_income = TaxCalculator._safe_decimal(available_fields.get("total_other_income"))
        if total_other_income is None:
            total_other_income = house_property_income + other_sources_income

        gross_total_income = max(Decimal("0"), income_under_salary + total_other_income)

        chapter_via_total_deductions = TaxCalculator._sum_fields(
            available_fields,
            [
                "deductions_80c",
                "deductions_80ccc",
                "deductions_80ccd_1",
                "deductions_80ccd_1b",
                "deductions_80ccd_2",
                "deductions_80d",
                "deductions_80e",
                "deductions_80g",
                "deductions_80tta",
                "deductions_other",
                "manual_deductions",
            ],
        )

        taxable_income = max(Decimal("0"), gross_total_income - chapter_via_total_deductions)
        tax_on_total_income, slab_breakdown = TaxCalculator._calculate_slab_tax(float(taxable_income), slabs)

        section_87a_rebate = Decimal(str(rebate_amount if float(taxable_income) <= rebate_threshold else 0))

        # Always compute surcharge/cess from current slab tax to avoid stale extracted values.
        surcharge = Decimal("0")
        health_education_cess = Decimal(str((tax_on_total_income + float(surcharge)) * health_cess_rate))

        tax_payable = max(0.0, tax_on_total_income + float(surcharge) + float(health_education_cess) - float(section_87a_rebate))
        relief_89 = TaxCalculator._safe_decimal(available_fields.get("relief_89")) or Decimal("0")
        net_payable_tax = max(0.0, tax_payable - float(relief_89))
        tds = TaxCalculator._safe_decimal(available_fields.get("tds")) or Decimal("0")

        return {
            "regime": "Old Regime",
            "gross_income": float(gross_income),
            "fiscal_year": fiscal_year,
            "standard_deduction": standard_deduction,
            "section_10_allowance": float(section_10_allowance),
            "salary_after_section10_exemptions": float(salary_after_section10_exemptions),
            "entertainment_allowance": float(entertainment_allowance),
            "professional_tax": float(professional_tax),
            "total_section16_deductions": float(total_section16_deductions),
            "income_under_salary": float(income_under_salary),
            "total_other_income": float(total_other_income),
            "gross_total_income": float(gross_total_income),
            "chapter_via_total_deductions": float(chapter_via_total_deductions),
            "taxable_income": float(taxable_income),
            "tax_on_total_income": float(tax_on_total_income),
            "tax_slab_breakdown": slab_breakdown,
            "section_87a_rebate": float(section_87a_rebate),
            "surcharge": float(surcharge),
            "health_education_cess": float(health_education_cess),
            "tax_payable": float(tax_payable),
            "relief_89": float(relief_89),
            "net_payable_tax": float(net_payable_tax),
            "tds": float(tds),
            "total_tax": float(net_payable_tax),
            "tax_after_tds": max(0.0, float(net_payable_tax) - float(tds)),
            "in_hand": float(gross_income) - float(net_payable_tax),
            "effective_rate": round((float(net_payable_tax) / float(gross_income) * 100), 2) if gross_income > 0 else 0,
            "source": "calculated",
        }

    @staticmethod
    def _calculate_new_regime_tax(
        available_fields: Dict[str, Decimal],
        gross_income: float,
        fiscal_year: str,
        rules: Dict,
        health_cess_rate: float = 0.04,
    ) -> Dict:
        """Calculate tax for new regime with only standard deduction."""
        standard_deduction_raw = rules.get("standard_deduction")
        if standard_deduction_raw is None:
            raise ValueError("Missing standard_deduction in tax_slabs.json for new_regime")
        standard_deduction = float(standard_deduction_raw)
        slabs = rules.get("slabs", [])
        rebate_config = (rules.get("rebate") or {}).get("section_87a", {})
        rebate_amount = float(rules.get("rebate_amount", rebate_config.get("amount", 0)) or 0)
        rebate_threshold = float(rules.get("rebate_threshold", rebate_config.get("threshold", 0)) or 0)


        income_under_salary = max(Decimal("0"), Decimal(str(gross_income)) - Decimal(str(standard_deduction)))

        house_property_income = TaxCalculator._safe_decimal(available_fields.get("house_property_income")) or Decimal("0")
        other_sources_income = TaxCalculator._safe_decimal(available_fields.get("other_sources_income")) or Decimal("0")
        total_other_income = TaxCalculator._safe_decimal(available_fields.get("total_other_income"))
        if total_other_income is None:
            total_other_income = house_property_income + other_sources_income

        gross_total_income = max(Decimal("0"), income_under_salary + total_other_income)

        tax_on_total_income, slab_breakdown = TaxCalculator._calculate_slab_tax(float(gross_total_income), slabs)

        section_87a_rebate = Decimal(str(rebate_amount if float(gross_total_income) <= rebate_threshold else 0))

        # Always compute surcharge/cess from current slab tax to avoid stale extracted values.
        surcharge = Decimal("0")
        health_education_cess = Decimal(str((tax_on_total_income + float(surcharge)) * health_cess_rate))

        tax_payable = max(0.0, tax_on_total_income + float(surcharge) + float(health_education_cess) - float(section_87a_rebate))
        relief_89 = TaxCalculator._safe_decimal(available_fields.get("relief_89")) or Decimal("0")
        net_payable_tax = max(0.0, tax_payable - float(relief_89))
        tds = TaxCalculator._safe_decimal(available_fields.get("tds")) or Decimal("0")

        return {
            "regime": "New Regime",
            "gross_income": float(gross_income),
            "fiscal_year": fiscal_year,
            "standard_deduction": standard_deduction,
            "income_under_salary": float(income_under_salary),
            "total_other_income": float(total_other_income),
            "taxable_income": float(gross_total_income),
            "tax_on_total_income": float(tax_on_total_income),
            "tax_slab_breakdown": slab_breakdown,
            "section_87a_rebate": float(section_87a_rebate),
            "surcharge": float(surcharge),
            "health_education_cess": float(health_education_cess),
            "tax_payable": float(tax_payable),
            "relief_89": float(relief_89),
            "net_payable_tax": float(net_payable_tax),
            "tds": float(tds),
            "tax_after_tds": max(0.0, float(net_payable_tax) - float(tds)),
            "in_hand": float(gross_income) - float(net_payable_tax),
            "effective_rate": round((float(net_payable_tax) / float(gross_income) * 100), 2) if gross_income > 0 else 0,
            "source": "calculated",
        }

    @staticmethod
    def _calculate_slab_tax(taxable_income: float, slabs: List[Dict]) -> Tuple[float, List[Dict]]:
        """Calculate slab-wise tax and return a structured breakdown."""
        tax = 0.0
        previous_limit = 0.0
        breakdown = []

        for slab in slabs:
            slab_max = float("inf") if slab.get("max") is None else float(slab.get("max"))
            configured_min = float(slab.get("min", previous_limit))
            slab_min = previous_limit if configured_min > previous_limit else configured_min
            rate = float(slab.get("rate", 0))
            taxable_from_slab = max(0.0, min(taxable_income, slab_max) - slab_min)
            if taxable_from_slab > 0:
                slab_tax = taxable_from_slab * rate
                tax += slab_tax
                breakdown.append({
                    "from": slab_min,
                    "to": None if slab_max == float("inf") else slab_max,
                    "rate": rate,
                    "taxable_amount": taxable_from_slab,
                    "tax": slab_tax,
                })
            if slab_max != float("inf"):
                previous_limit = slab_max

        return tax, breakdown
    
    @staticmethod
    def compare_regimes(gross_income: float, deductions: float = 0, fiscal_year: str = "2026-27") -> Dict:
        """Compare tax liability in both regimes and recommend the better one."""
        rules = TaxCalculator._get_rules(fiscal_year)
        health_cess_rate = rules.get("health_cess_rate", TaxCalculator.DEFAULT_HEALTH_CESS_RATE)

        available_fields = {
            "manual_deductions": TaxCalculator._safe_decimal(deductions) or Decimal("0"),
        }

        new_regime = TaxCalculator._calculate_new_regime_tax(
            available_fields=available_fields,
            gross_income=gross_income,
            fiscal_year=fiscal_year,
            rules=rules.get("new_regime", {}),
            health_cess_rate=health_cess_rate,
        )
        old_regime = TaxCalculator._calculate_old_regime_tax(
            available_fields=available_fields,
            gross_income=gross_income,
            fiscal_year=fiscal_year,
            rules=rules.get("old_regime", {}),
            health_cess_rate=health_cess_rate,
        )
        
        savings_with_old = new_regime['net_payable_tax'] - old_regime['net_payable_tax']
        recommended_regime = "Old Regime" if savings_with_old > 0 else "New Regime"
        
        return {
            "gross_income": gross_income,
            "fiscal_year": fiscal_year,
            "deductions_claimed": deductions,
            "new_regime": new_regime,
            "old_regime": old_regime,
            "comparison": {
                "new_regime_tax": new_regime['net_payable_tax'],
                "old_regime_tax": old_regime['net_payable_tax'],
                "savings_with_old_regime": max(0, savings_with_old),
                "savings_with_new_regime": max(0, -savings_with_old),
                "recommended_regime": recommended_regime,
                "recommendation_reason": f"Choose {recommended_regime} to save ₹{abs(savings_with_old):,.2f}" if abs(savings_with_old) > 0 else "Both regimes result in similar tax liability"
            }
        }
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Safely convert a value to float, returning None if not possible"""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def validate_extracted_vs_calculated(form16_extraction, regime: str = "old") -> Dict:
        """Validate extracted tax values against calculated values
        
        Args:
            form16_extraction: Form16Extraction model instance
            regime: "old" or "new"
        
        Returns:
            Dictionary with validation results and variance analysis
        """
        try:
            fiscal_year = getattr(form16_extraction, "financial_year", None) or TaxCalculator.DEFAULT_FISCAL_YEAR
            deduction_breakdown = {
                "section_80c": TaxCalculator._safe_float(form16_extraction.deductions_80c) or 0,
                "section_80d": TaxCalculator._safe_float(form16_extraction.deductions_80d) or 0,
                "section_80e": TaxCalculator._safe_float(form16_extraction.deductions_80e_ccd_1) or 0,
                "section_80ccc": TaxCalculator._safe_float(form16_extraction.deductions_80ccc) or 0,
                "section_80ccd_1": TaxCalculator._safe_float(form16_extraction.deductions_80ccd_1) or 0,
                "section_80ccd_1b": TaxCalculator._safe_float(form16_extraction.deductions_80ccd_1b) or 0,
                "section_80ccd_2": TaxCalculator._safe_float(form16_extraction.deductions_80ccd_2) or 0,
                "entertainment_allowance_16": TaxCalculator._safe_float(form16_extraction.entertainment_allowance_16) or 0,
                "professional_tax_16": TaxCalculator._safe_float(form16_extraction.professional_tax_16) or 0,
                "standard_deduction": TaxCalculator._safe_float(form16_extraction.standard_deduction) or 0,
                "donations_80g": TaxCalculator._safe_float(form16_extraction.donations_80g) or 0,
                "chapter_vi_a_total": TaxCalculator._safe_float(form16_extraction.chapter_via_total_deductions) or 0,
                "total_deductions_chapter_vi_a": TaxCalculator._safe_float(form16_extraction.chapter_via_total_deductions) or 0,
            }
            total_deductions = sum(deduction_breakdown.values())
            calculation = TaxCalculator.calculate_tax(
                form16_extraction=form16_extraction,
                fiscal_year=fiscal_year,
                regime=regime,
                deductions=total_deductions if regime == "old" else 0,
            )
            
            if "error" in calculation:
                return {"error": calculation["error"]}
            regime_result = calculation.get(f"{regime}_regime", {})

            # Validate only values produced by calculator and available in extraction.
            candidate_fields = {
                "gross_total_income": TaxCalculator._safe_float(getattr(form16_extraction, "gross_total_income", None)),
                "taxable_income": TaxCalculator._safe_float(getattr(form16_extraction, "taxable_income", None)),
                "tax_payable": TaxCalculator._safe_float(getattr(form16_extraction, "tax_payable", None)),
                "tds": TaxCalculator._safe_float(getattr(form16_extraction, "tds", None)),
            }

            validated_fields = {}
            for field_name, extracted_value in candidate_fields.items():
                calculated_value_raw = regime_result.get(field_name)
                calculated_value = TaxCalculator._safe_float(calculated_value_raw)
                if extracted_value is None or calculated_value is None:
                    continue

                variance = abs(extracted_value - calculated_value)
                variance_percentage = (variance / max(extracted_value, calculated_value, 1)) * 100
                validated_fields[field_name] = {
                    "extracted": extracted_value,
                    "calculated": calculated_value,
                    "variance": variance,
                    "variance_percentage": round(variance_percentage, 2),
                    "status": "Match" if variance_percentage < 5 else ("Close" if variance_percentage < 15 else "Variance"),
                }

            if not validated_fields:
                return {
                    "error": "No overlapping calculable fields available for validation",
                    "extraction_id": form16_extraction.extraction_id,
                    "regime": regime,
                }

            primary_field = "tax_payable" if "tax_payable" in validated_fields else next(iter(validated_fields))
            primary = validated_fields[primary_field]
            income_components = {
                "salary_income": TaxCalculator._safe_float(form16_extraction.income_under_salary) or 0,
                "house_property_income": TaxCalculator._safe_float(form16_extraction.house_property_income) or 0,
                "other_sources_income": TaxCalculator._safe_float(form16_extraction.other_sources_income) or 0,
                "gross_salary": TaxCalculator._safe_float(form16_extraction.gross_salary) or 0,
                "gross_total_income": TaxCalculator._safe_float(form16_extraction.gross_total_income) or 0,
                "salary_section_17_1": TaxCalculator._safe_float(form16_extraction.salary_section_17_1) or 0,
                "perquisites_17_2": TaxCalculator._safe_float(form16_extraction.perquisites_17_2),
                "profits_in_lieu_17_3": TaxCalculator._safe_float(form16_extraction.profits_in_lieu_17_3),
            }
            
            return {
                "extraction_id": form16_extraction.extraction_id,
                "regime": regime,
                "validation_basis": primary_field,
                "extracted_tax": primary["extracted"],
                "calculated_tax": primary["calculated"],
                "variance": primary["variance"],
                "variance_percentage": primary["variance_percentage"],
                "status": primary["status"],
                "validated_fields": validated_fields,
                "extraction_breakdown": deduction_breakdown,
                "income_components": income_components,
                "full_calculation": regime_result,
            }
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {"error": f"Validation failed: {str(e)}"}
