"""Tax calculation engine for Old and New tax regimes"""

import logging
from typing import Dict, Optional
from services.tax_slab_loader import TaxSlabLoader

logger = logging.getLogger(__name__)


class TaxCalculator:
    """Calculate income tax for both Old and New regimes using JSON-based slabs"""
    
    # Default fiscal year if not specified
    DEFAULT_FISCAL_YEAR = "2026-27"
    
    @staticmethod
    def _calculate_tax_base(gross_income: float, regime: str, deductions: float = 0, fiscal_year: str = "2026-27") -> Dict:
        """Core calculation engine shared by both regimes"""
        
        # 1. Load configuration from JSON
        standard_deduction = TaxSlabLoader.get_standard_deduction(fiscal_year, regime)
        slabs = TaxSlabLoader.get_slabs_list(fiscal_year, regime)
        if not slabs:
            slabs = TaxSlabLoader.get_slabs_list(TaxCalculator.DEFAULT_FISCAL_YEAR, regime)
        
        # 2. Taxable Income Calculation
        taxable_income = max(0, gross_income - standard_deduction - deductions)
        
        # 3. Slab Iteration
        federal_tax = 0
        remaining = taxable_income
        prev_limit = 0
        for slab_limit, rate in slabs:
            if remaining <= 0: break
            taxable_in_slab = min(remaining, slab_limit - prev_limit)
            federal_tax += taxable_in_slab * rate
            remaining -= taxable_in_slab
            prev_limit = slab_limit
        
        # 4. Final Totals
        health_cess_rate = TaxSlabLoader.get_health_cess_rate(fiscal_year)
        cess = federal_tax * health_cess_rate
        total_tax = federal_tax + cess
        
        return {
            "regime": "New Regime" if regime == "new_regime" else "Old Regime",
            "fiscal_year": fiscal_year,
            "gross_income": gross_income,
            "taxable_income": taxable_income,
            "standard_deduction": standard_deduction,
            "total_tax": total_tax,
            "cess": cess,
            "federal_tax": federal_tax,
            "in_hand": gross_income - total_tax,
            "effective_rate": round((total_tax / gross_income * 100), 2) if gross_income > 0 else 0
        }

    @staticmethod
    def calculate_new_regime(gross_income: float, fiscal_year: str = "2026-27") -> Dict:
        # New regime typically doesn't allow 'deductions' like 80C
        return TaxCalculator._calculate_tax_base(gross_income, "new_regime", 0, fiscal_year)

    @staticmethod
    def calculate_old_regime(gross_income: float, deductions: float = 0, fiscal_year: str = "2026-27", 
                            age: Optional[int] = None, section_80e_paid: float = 0, 
                            section_80g_paid: float = 0, section_80d_coverage_type: str = "self_and_family",
                            section_80d_parents_age: Optional[int] = None) -> Dict:
        """
        Calculate income tax for old regime with support for age-based deductions
        
        Args:
            gross_income: Annual gross income
            deductions: Total deductions (for backward compatibility)
            fiscal_year: Fiscal year in "YYYY-YY" format
            age: Age of taxpayer (for age-based deductions like 80D and 80TT)
            section_80e_paid: Actual education loan interest paid
            section_80g_paid: Actual charitable donations made
            section_80d_coverage_type: "self_and_family" or "self_family_and_parents"
            section_80d_parents_age: Age of parents (only relevant if coverage includes parents)
        
        Returns:
            Dictionary with tax calculation details
        """
        # If deductions are provided directly, use them (backward compatibility)
        if deductions > 0:
            return TaxCalculator._calculate_tax_base(gross_income, "old_regime", deductions, fiscal_year)
        
        # Otherwise, calculate deductions based on age and JSON configuration
        allowable_deductions = TaxSlabLoader.get_allowable_deductions(fiscal_year, "old_regime")
        
        if not allowable_deductions:
            # Fallback if JSON not available
            return TaxCalculator._calculate_tax_base(gross_income, "old_regime", 0, fiscal_year)
        
        # Calculate Section 80C
        section_80c_info = allowable_deductions.get("section_80c", {})
        max_80c = section_80c_info.get("max_amount", 150000) or 150000
        
        # Use based on income level
        if gross_income >= 1000000:
            section_80c_deduction = max_80c
        elif gross_income >= 500000:
            section_80c_deduction = min(max_80c, gross_income * 0.15)
        else:
            section_80c_deduction = min(max_80c, gross_income * 0.10)
        
        # Calculate Section 80D (based on coverage type and ages of all covered members)
        section_80d_info = allowable_deductions.get("section_80d", {})
        limit_options = section_80d_info.get("limit", {})
        
        # Determine the appropriate deduction limit based on:
        # 1. Coverage type (self & family vs. self, family & parents)
        # 2. Age of covered members (who is 60+)
        if section_80d_coverage_type == "self_family_and_parents":
            # Insurance covers self, family, AND parents
            # Check if both self and parents are senior citizens (60+)
            if (age and age >= 60) and (section_80d_parents_age and section_80d_parents_age >= 60):
                # All covered (self, family, parents) are age 60+
                section_80d_deduction = limit_options.get("senior_citizen_self_family_and_parents", 100000)
            elif section_80d_parents_age and section_80d_parents_age >= 60 and (not age or age < 60):
                # Self/family below 60, but parents are senior citizens (60+)
                section_80d_deduction = limit_options.get("senior_citizen_parents", 75000)
            else:
                # All covered members are below 60
                section_80d_deduction = limit_options.get("self_family_and_parents", 50000)
        else:
            # Insurance covers only self & family (no parents)
            # Amount is ₹25,000 for self & family below 60
            # Note: If self is 60+, it would still be self_and_family category with appropriate limit
            if age and age >= 60:
                # Senior citizen with self & family coverage
                # Using the highest limit for self & family not covered by other categories
                section_80d_deduction = 25000  # Stays same as self & family is primary category
            else:
                section_80d_deduction = limit_options.get("self_and_family", 25000) or 25000
        
        # Calculate Section 80E (only if actually paid)
        section_80e_deduction = section_80e_paid
        
        # Calculate Section 80G (only if actually paid)
        section_80g_deduction = section_80g_paid
        
        # Calculate Section 80GG
        section_80gg_info = allowable_deductions.get("section_80gg", {})
        gg_rules = section_80gg_info.get("rules", {})
        
        if gg_rules:
            gg_fixed = gg_rules.get("fixed_annual_deduction", 60000)
            gg_percentage_rent = gross_income * gg_rules.get("percentage_of_rent", 0.25)
            gg_percentage_income = gross_income * gg_rules.get("percentage_of_income", 0.10)
            section_80gg_deduction = min(gg_fixed, gg_percentage_rent, gg_percentage_income)
        else:
            section_80gg_deduction = 60000
        
        # Use based on income level
        if gross_income >= 1000000:
            section_80gg_deduction = section_80gg_deduction
        elif gross_income >= 500000:
            section_80gg_deduction = min(section_80gg_deduction, gross_income * 0.08)
        else:
            section_80gg_deduction = min(section_80gg_deduction, gross_income * 0.05)
        
        # Calculate Section 80TT (age-based)
        section_80tt_info = allowable_deductions.get("section_80tt", {})
        sub_sections = section_80tt_info.get("sub_sections", {})
        
        if age and age >= 60:
            max_80tt = sub_sections.get("80ttb", {}).get("max_amount", 50000)
            section_80tt_deduction = min(max_80tt, gross_income * 0.05)
        else:
            max_80tt = sub_sections.get("80tta", {}).get("max_amount", 10000)
            section_80tt_deduction = min(max_80tt, gross_income * 0.02)
        
        # Total deductions
        total_deductions = (section_80c_deduction + section_80d_deduction + section_80e_deduction + 
                           section_80g_deduction + section_80gg_deduction + section_80tt_deduction)
        
        result = TaxCalculator._calculate_tax_base(gross_income, "old_regime", total_deductions, fiscal_year)
        
        # Add deduction breakdown to result
        result["deduction_breakdown"] = {
            "section_80c": section_80c_deduction,
            "section_80d": section_80d_deduction,
            "section_80e": section_80e_deduction,
            "section_80g": section_80g_deduction,
            "section_80gg": section_80gg_deduction,
            "section_80tt": section_80tt_deduction,
            "total_deductions": total_deductions
        }
        
        return result
    
    @staticmethod
    def compare_regimes(gross_income: float, deductions: float = 0, fiscal_year: str = "2026-27", 
                       age: Optional[int] = None, section_80e_paid: float = 0, 
                       section_80g_paid: float = 0, section_80d_coverage_type: str = "self_and_family",
                       section_80d_parents_age: Optional[int] = None) -> Dict:
        """Compare tax liability in both regimes and recommend the better one"""
        new_regime = TaxCalculator.calculate_new_regime(gross_income, fiscal_year)
        old_regime = TaxCalculator.calculate_old_regime(gross_income, deductions, fiscal_year, age, 
                                                       section_80e_paid, section_80g_paid, 
                                                       section_80d_coverage_type, section_80d_parents_age)
        
        savings_with_old = new_regime['total_tax'] - old_regime['total_tax']
        recommended_regime = "Old Regime" if savings_with_old > 0 else "New Regime"
        
        return {
            "gross_income": gross_income,
            "fiscal_year": fiscal_year,
            "age": age,
            "section_80d_coverage_type": section_80d_coverage_type,
            "section_80d_parents_age": section_80d_parents_age,
            "deductions_claimed": deductions,
            "new_regime": new_regime,
            "old_regime": old_regime,
            "comparison": {
                "new_regime_tax": new_regime['total_tax'],
                "old_regime_tax": old_regime['total_tax'],
                "savings_with_old_regime": max(0, savings_with_old),
                "savings_with_new_regime": max(0, -savings_with_old),
                "recommended_regime": recommended_regime,
                "recommendation_reason": f"Choose {recommended_regime} to save ₹{abs(savings_with_old):,.2f}" if abs(savings_with_old) > 0 else "Both regimes result in similar tax liability"
            }
        }
    
    @staticmethod
    def suggest_deductions(gross_income: float, fiscal_year: str = "2026-27", age: Optional[int] = None,
                          section_80d_coverage_type: str = "self_and_family",
                          section_80d_parents_age: Optional[int] = None) -> Dict:
        """
        Suggest optimal deductions for the user based on income, fiscal year, and age
        
        Args:
            gross_income: Annual gross income
            fiscal_year: Fiscal year in "YYYY-YY" format
            age: Age of taxpayer
            section_80d_coverage_type: "self_and_family" or "self_family_and_parents"
            section_80d_parents_age: Age of parents (if covered by insurance)
        """
        # Get allowable deductions from JSON
        allowable_deductions = TaxSlabLoader.get_allowable_deductions(fiscal_year, "old_regime")
        
        if not allowable_deductions:
            return {"error": "Could not load deductions from tax slabs"}
        
        # Section 80C - Investment in Specified Securities
        section_80c_info = allowable_deductions.get("section_80c", {})
        max_80c = section_80c_info.get("max_amount", 150000) or 150000
        
        # Section 80D - Health Insurance Premium (based on coverage type and ages of covered members)
        section_80d_info = allowable_deductions.get("section_80d", {})
        limit_options = section_80d_info.get("limit", {})
        
        # Determine section 80D category and max limit based on both factors
        if section_80d_coverage_type == "self_family_and_parents":
            # Insurance covers self, family, AND parents
            if (age and age >= 60) and (section_80d_parents_age and section_80d_parents_age >= 60):
                # All covered (self, family, parents) are age 60+
                max_80d = limit_options.get("senior_citizen_self_family_and_parents", 100000)
                section_80d_category = "Self, family & parents (all above 60 years)"
            elif section_80d_parents_age and section_80d_parents_age >= 60 and (not age or age < 60):
                # Self/family below 60, but parents are senior citizens (60+)
                max_80d = limit_options.get("senior_citizen_parents", 75000)
                section_80d_category = "Self, family (below 60) & senior citizen parents"
            else:
                # All covered members are below 60
                max_80d = limit_options.get("self_family_and_parents", 50000)
                section_80d_category = "Self, family & parents (all below 60)"
        else:
            # Insurance covers only self & family (no parents)
            max_80d = limit_options.get("self_and_family", 25000) or 25000
            section_80d_category = "Self & family (below 60 years)"
        
        # Section 80E - Education Loan Interest (only if actually paid, no fixed limit)
        section_80e_info = allowable_deductions.get("section_80e", {})
        
        # Section 80G - Charitable Donations (only if actually paid, no specific fixed limit)
        section_80g_info = allowable_deductions.get("section_80g", {})
        
        # Section 80GG - Rent Paid (lowest of the rules)
        section_80gg_info = allowable_deductions.get("section_80gg", {})
        gg_rules = section_80gg_info.get("rules", {})
        
        # Calculate 80GG deduction as minimum of:
        # - fixed_annual_deduction: 60000
        # - 25% of rent paid
        # - 10% of income
        if gg_rules:
            gg_fixed = gg_rules.get("fixed_annual_deduction", 60000)
            gg_percentage_rent = gross_income * gg_rules.get("percentage_of_rent", 0.25)  # Assuming average rent
            gg_percentage_income = gross_income * gg_rules.get("percentage_of_income", 0.10)
            max_80gg = min(gg_fixed, gg_percentage_rent, gg_percentage_income)
        else:
            max_80gg = 60000
        
        # Section 80TT - Interest on Savings/Deposits (age-based sub-sections)
        section_80tt_info = allowable_deductions.get("section_80tt", {})
        sub_sections = section_80tt_info.get("sub_sections", {})
        
        # Determine which 80TT sub-section applies
        if age and age >= 60:
            # Senior citizen - use 80TTB
            max_80tt = sub_sections.get("80ttb", {}).get("max_amount", 50000)
            section_80tt_applicable = "80TTB (Senior Citizens)"
            section_80tt_includes = sub_sections.get("80ttb", {}).get("includes", [])
        else:
            # General citizen - use 80TTA
            max_80tt = sub_sections.get("80tta", {}).get("max_amount", 10000)
            section_80tt_applicable = "80TTA (General)"
            section_80tt_includes = sub_sections.get("80tta", {}).get("includes", [])
        
        # Suggest deductions based on income
        # Note: 80E and 80G are only applicable if actually paid
        if gross_income >= 1000000:
            suggested_80c = max_80c
            suggested_80d = max_80d
            suggested_80e = 0  # Only if actually paid
            suggested_80g = 0  # Only if actually paid
            suggested_80gg = max_80gg
            suggested_80tt = max_80tt
        elif gross_income >= 500000:
            suggested_80c = min(max_80c, gross_income * 0.15)
            suggested_80d = max_80d
            suggested_80e = 0  # Only if actually paid
            suggested_80g = 0  # Only if actually paid
            suggested_80gg = min(max_80gg, gross_income * 0.08)
            suggested_80tt = min(max_80tt, gross_income * 0.05)
        else:
            suggested_80c = min(max_80c, gross_income * 0.10)
            suggested_80d = min(max_80d, 10000)
            suggested_80e = 0  # Only if actually paid
            suggested_80g = 0  # Only if actually paid
            suggested_80gg = min(max_80gg, gross_income * 0.05)
            suggested_80tt = min(max_80tt, gross_income * 0.02)
        
        total_suggested = (suggested_80c + suggested_80d + suggested_80e + 
                          suggested_80g + suggested_80gg + suggested_80tt)
        
        return {
            "gross_income": gross_income,
            "fiscal_year": fiscal_year,
            "age": age,
            "section_80d_coverage_type": section_80d_coverage_type,
            "section_80d_parents_age": section_80d_parents_age,
            "suggested_deductions": {
                "section_80c": {
                    "name": section_80c_info.get("name", "Investment in Specified Securities"),
                    "amount": suggested_80c,
                    "max_limit": max_80c,
                    "includes": section_80c_info.get("includes", []),
                    "description": section_80c_info.get("description", "Various investment options")
                },
                "section_80d": {
                    "name": section_80d_info.get("name", "Health Insurance Premium"),
                    "amount": suggested_80d,
                    "max_limit": max_80d,
                    "category": section_80d_category,
                    "coverage_type": section_80d_coverage_type,
                    "self_age": age,
                    "parents_age": section_80d_parents_age,
                    "available_limits": limit_options,
                    "description": section_80d_info.get("description", "Health insurance premiums based on coverage type and age")
                },
                "section_80e": {
                    "name": section_80e_info.get("name", "Education Loan Interest"),
                    "amount": suggested_80e,
                    "max_limit": section_80e_info.get("max_amount", "Unlimited"),
                    "note": "Only applicable if you have paid education loan interest",
                    "description": section_80e_info.get("description", "Education loan interest deduction - no set limit")
                },
                "section_80g": {
                    "name": section_80g_info.get("name", "Charitable Donations"),
                    "amount": suggested_80g,
                    "max_limit": section_80g_info.get("max_amount", "50-100% of donations"),
                    "note": "Only applicable if you have made qualifying charitable donations",
                    "description": section_80g_info.get("description", "Charitable donations deduction - 50% or 100% depending on donation type")
                },
                "section_80gg": {
                    "name": section_80gg_info.get("name", "Rent Paid"),
                    "amount": suggested_80gg,
                    "max_limit": max_80gg,
                    "rules": gg_rules,
                    "rules_explanation": "Lowest of: fixed amount (₹60,000), 25% of rent paid, or 10% of income",
                    "description": section_80gg_info.get("description", "Rent paid deduction")
                },
                "section_80tt": {
                    "name": section_80tt_info.get("name", "Interest on Savings/Deposits"),
                    "amount": suggested_80tt,
                    "max_limit": max_80tt,
                    "applicable_sub_section": section_80tt_applicable,
                    "includes": section_80tt_includes,
                    "description": section_80tt_info.get("description", "Interest from savings/deposits")
                }
            },
            "total_suggested_deductions": total_suggested,
            "potential_tax_saving": {
                "old_regime_benefit": total_suggested * 0.30,  # Rough estimate at 30% tax bracket
                "note": "Actual savings depend on your applicable tax bracket"
            }
        }
