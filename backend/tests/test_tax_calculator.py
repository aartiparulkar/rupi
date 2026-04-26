"""Basic placeholder tests for tax calculator service."""

from services.tax_calculator import TaxCalculator


class _ExtractionStub:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_compare_regimes_returns_comparison_key():
    result = TaxCalculator.calculate_tax(gross_income=1000000, deductions=150000, fiscal_year="2026-27", regime="both")
    assert "comparison" in result


def test_uses_supabase_extracted_tax_when_present():
    extraction = _ExtractionStub(
        extraction_id="x1",
        classified_document_type="form16",
        financial_year="2026-27",
        gross_total_income=1000000,
        taxable_income=700000,
        tax_payable=52000,
        net_payable_tax=52000,
        health_education_cess=2000,
        surcharge=0,
        relief_89=0,
        section_87a_rebate=0,
        tds=10000,
    )

    result = TaxCalculator.calculate_tax(form16_extraction=extraction, regime="old")

    assert result["data_source"]["old_regime"] == "supabase_extracted"
    assert result["old_regime"]["source"] == "supabase_extracted"
    assert result["old_regime"]["total_tax"] == 52000


def test_falls_back_to_calculated_when_extracted_tax_missing():
    extraction = _ExtractionStub(
        extraction_id="x2",
        classified_document_type="form16",
        financial_year="2026-27",
        gross_total_income=1000000,
        deductions_80c=100000,
    )

    result = TaxCalculator.calculate_tax(form16_extraction=extraction, regime="old")

    assert result["data_source"]["old_regime"] == "calculated"
    assert result["old_regime"].get("source") is None
    assert "total_tax" in result["old_regime"]
