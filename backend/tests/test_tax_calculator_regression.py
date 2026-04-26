from services.tax_calculator import TaxCalculator


def test_new_regime_ignores_extracted_cess_for_computed_tax():
    extraction_like = {
        "gross_salary": 1680000,
        "total_other_income": 10000,
        "health_education_cess": 7100,
        "tax_payable": 184600,
    }

    result = TaxCalculator.calculate_tax(
        form16_extraction=extraction_like,
        fiscal_year="2026-27",
        regime="new",
    )

    new_regime = result["new_regime"]
    assert round(new_regime["tax_on_total_income"], 2) == 123000.00
    assert round(new_regime["health_education_cess"], 2) == 4920.00
    assert round(new_regime["net_payable_tax"], 2) == 127920.00


def test_slab_tax_handles_non_contiguous_configured_mins():
    slabs = [
        {"min": 0, "max": 400000, "rate": 0.0},
        {"min": 400001, "max": 800000, "rate": 0.05},
    ]

    tax, _ = TaxCalculator._calculate_slab_tax(800000, slabs)
    assert round(tax, 2) == 20000.00
