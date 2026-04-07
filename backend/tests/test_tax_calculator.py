"""Basic placeholder tests for tax calculator service."""

from services.tax_calculator import TaxCalculator


def test_compare_regimes_returns_comparison_key():
    result = TaxCalculator.compare_regimes(1000000, 150000, "2026-27")
    assert "comparison" in result
