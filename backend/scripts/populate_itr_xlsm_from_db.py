"""Populate the ITR xlsm template from Form16 extraction data stored in DB.

The workbook is a macro-enabled template with named cells. This script fills the
main named inputs, writes extracted/calculated values into the output cells, and
sets unknown numeric inputs to 0.

Examples:
  python backend/scripts/populate_itr_xlsm_from_db.py
  python backend/scripts/populate_itr_xlsm_from_db.py --extraction-id <uuid>
  python backend/scripts/populate_itr_xlsm_from_db.py --user-id <user-id>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.database import Form16Extraction, SessionLocal
from services.tax_calculator import TaxCalculator


DEFAULT_TEMPLATE = BACKEND_ROOT / "ITR1_AY_25-26_V1.7.xlsm"
DEFAULT_OUTPUT = BACKEND_ROOT / "sample_documents" / "ITR1_filled_from_db.xlsm"
DEFAULT_FISCAL_YEAR = "2024-25"


PERSONAL_NAME_MAP = {
    "sheet1.FirstName": "first_name",
    "sheet1.MiddleName": "middle_name",
    "sheet1.SurNameOrOrgName": "last_name",
    "sheet1.PAN": "pan",
    "Sheet1.Aadhaar": "aadhaar",
    "sheet1.DOB": "dob",
    "sheet1.Mobileno": "mobile_no",
    "sheet1.EmailAddress": "email_address",
    "sheet1.ResidentialStatus1": "residential_status",
    "sheet1.Gender1": "gender",
    "sheet1.EmployerCategory1": "employer_category",
}

CALCULATION_NAME_MAP = {
    "IncD.IncomeFromSal": "income_from_salary",
    "IncD.IncomeHeadHouseProperty": "house_property_income",
    "IncD.IncomeFromOS": "other_sources_income",
    "IncD.StandardDeduction": "standard_deduction",
    "IncD.Deduction16": "deduction16_total",
    "IncD.TotalChapVIADeductions": "chapter_via_total_deductions",
    "IncD.TotalChapVIADeductions_Input": "chapter_via_total_deductions",
    "IncD.GrossTotIncome": "gross_total_income",
    "IncD.TotalIncome": "gross_total_income",
    "IncD.TotalIncome_New": "gross_total_income",
    "IncD.TotalTaxPayable": "tax_payable",
    "IncD.TaxPayableOnRebate": "section_87a_rebate",
    "IncD.SurchargeOnTaxPayable": "surcharge",
    "IncD.GrossTaxLiability": "gross_tax_liability",
    "IncD.NetTaxLiability": "net_payable_tax",
    "IncD.TotTaxPlusIntrstPay": "net_payable_tax",
    "IncD.TDS": "tds",
    "IncD.TotalTaxesPaid": "total_taxes_paid",
    "IncD.AdvanceTax": "advance_tax",
    "IncD.SelfAssessmentTax": "self_assessment_tax",
    "IncD.BalTaxPayable": "amount_payable",
}

ZERO_FILL_SHEETS = {
    "Income Details",
    "Taxes Paid and Verification",
    "TDS",
    "TCS",
    "Part A Gen_139(8A)",
    "Part B ATI",
    "Schedule EA 10(13A)",
    "Schedule 24(b)",
    "80D",
    "80G",
    "80GGA",
    "80GGC",
    "80U-80DD",
    "80C",
    "80E_80EE_80EEA_80EEB",
}


@dataclass
class PopulatedWorkbook:
    extraction_id: Optional[str]
    template_path: str
    output_path: str
    assessment_year: str
    fiscal_year: str


def _to_primitive(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _split_employee_name(employee_name: Optional[str]) -> Tuple[str, str, str]:
    if not employee_name:
        return "0", "0", "0"

    parts = [part for part in re.split(r"\s+", employee_name.strip()) if part]
    if not parts:
        return "0", "0", "0"
    if len(parts) == 1:
        return parts[0], "0", "0"
    if len(parts) == 2:
        return parts[0], "0", parts[1]
    return parts[0], parts[1], " ".join(parts[2:])


def _lookup_defined_name(workbook, target_name: str):
    if target_name in workbook.defined_names:
        return workbook.defined_names[target_name]

    lowered = target_name.lower()
    for defined_name in workbook.defined_names.keys():
        if defined_name.lower() == lowered:
            return workbook.defined_names[defined_name]
    return None


def _set_defined_name(workbook, target_name: str, value: Any) -> bool:
    defined_name = _lookup_defined_name(workbook, target_name)
    if not defined_name:
        return False

    destinations = list(defined_name.destinations)
    if not destinations:
        return False

    sheet_name, cell_ref = destinations[0]
    if not sheet_name or not cell_ref:
        return False

    worksheet = workbook[sheet_name]
    target_cell = worksheet[cell_ref]
    if isinstance(target_cell, MergedCell):
        for merged_range in worksheet.merged_cells.ranges:
            if cell_ref in merged_range:
                target_cell = worksheet[merged_range.start_cell.coordinate]
                break

    target_cell.value = value
    return True


def _extract_row_payload(row: Form16Extraction) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for column in row.__table__.columns:
        payload[column.name] = _to_primitive(getattr(row, column.name, None))
    return payload


def _get_payload_value(payload: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _build_calculation_context(row: Form16Extraction, fiscal_year: str) -> Dict[str, Any]:
    calculation = TaxCalculator.calculate_tax(
        form16_extraction=row,
        fiscal_year=fiscal_year,
        regime="both",
    )
    return calculation


def _score_result_coverage(result: Dict[str, Any]) -> int:
    score = 0
    for payload_key in set(CALCULATION_NAME_MAP.values()):
        if result.get(payload_key) is not None:
            score += 1
    return score


def _select_relevant_result(calculation: Dict[str, Any]) -> Dict[str, Any]:
    old_result = calculation.get("old_regime") or {}
    new_result = calculation.get("new_regime") or {}

    if old_result and not new_result:
        return old_result
    if new_result and not old_result:
        return new_result
    if not old_result and not new_result:
        return {}

    old_score = _score_result_coverage(old_result)
    new_score = _score_result_coverage(new_result)
    if old_score > new_score:
        return old_result
    if new_score > old_score:
        return new_result

    recommended = str((calculation.get("comparison") or {}).get("recommended_regime") or "").lower()
    if "old" in recommended:
        return old_result
    if "new" in recommended:
        return new_result

    return old_result


def _resolve_numeric_value(
    workbook,
    target_name: str,
    payload: Dict[str, Any],
    calculation_result: Dict[str, Any],
) -> Any:
    if target_name in CALCULATION_NAME_MAP:
        mapped_key = CALCULATION_NAME_MAP[target_name]
        if mapped_key == "total_taxes_paid":
            value = _get_payload_value(payload, "tds")
            return value if value is not None else calculation_result.get("tds", 0) or 0
        if mapped_key == "amount_payable":
            value = _get_payload_value(payload, "tax_payable", "net_payable_tax")
            return value if value is not None else calculation_result.get("tax_payable", 0) or 0
        if mapped_key == "gross_tax_liability":
            value = _get_payload_value(payload, "tax_payable")
            if value is not None:
                return value
            tax_on_total_income = calculation_result.get("tax_on_total_income", 0) or 0
            surcharge = calculation_result.get("surcharge", 0) or 0
            cess = calculation_result.get("health_education_cess", 0) or 0
            rebate = calculation_result.get("section_87a_rebate", 0) or 0
            return max(0, float(tax_on_total_income) + float(surcharge) + float(cess) - float(rebate))

        value = _get_payload_value(payload, mapped_key)
        if value is None:
            value = calculation_result.get(mapped_key)
        if value is not None:
            return value

    return 0


def _populate_personal_fields(workbook, payload: Dict[str, Any]) -> None:
    employee_name = str(payload.get("employee_name") or "").strip()
    first_name, middle_name, last_name = _split_employee_name(employee_name)

    personal_values = {
        "sheet1.FirstName": first_name,
        "sheet1.MiddleName": middle_name,
        "sheet1.SurNameOrOrgName": last_name,
        "sheet1.PAN": payload.get("pan") or "0",
        "Sheet1.Aadhaar": payload.get("aadhaar") or "0",
        "sheet1.DOB": payload.get("dob") or "0",
        "sheet1.Mobileno": payload.get("mobile_no") or "0",
        "sheet1.EmailAddress": payload.get("email_address") or "0",
        "sheet1.ResidentialStatus1": payload.get("residential_status") or 0,
        "sheet1.Gender1": payload.get("gender") or 0,
        "sheet1.EmployerCategory1": payload.get("employer_category") or 0,
    }

    for name, value in personal_values.items():
        _set_defined_name(workbook, name, value)


def _populate_calculation_fields(workbook, payload: Dict[str, Any], calculation_result: Dict[str, Any]) -> None:
    # Explicit core inputs and outputs used by the workbook formulas.
    explicit_values = {
        "IncD.IncomeFromSal": _resolve_numeric_value(workbook, "IncD.IncomeFromSal", payload, calculation_result),
        "IncD.IncomeHeadHouseProperty": _resolve_numeric_value(workbook, "IncD.IncomeHeadHouseProperty", payload, calculation_result),
        "IncD.IncomeFromOS": _resolve_numeric_value(workbook, "IncD.IncomeFromOS", payload, calculation_result),
        "IncD.StandardDeduction": _resolve_numeric_value(workbook, "IncD.StandardDeduction", payload, calculation_result),
        "IncD.Deduction16": _resolve_numeric_value(workbook, "IncD.Deduction16", payload, calculation_result),
        "IncD.TotalChapVIADeductions": _resolve_numeric_value(workbook, "IncD.TotalChapVIADeductions", payload, calculation_result),
        "IncD.TotalChapVIADeductions_Input": _resolve_numeric_value(workbook, "IncD.TotalChapVIADeductions_Input", payload, calculation_result),
        "IncD.GrossTotIncome": _resolve_numeric_value(workbook, "IncD.GrossTotIncome", payload, calculation_result),
        "IncD.TotalIncome": _resolve_numeric_value(workbook, "IncD.TotalIncome", payload, calculation_result),
        "IncD.TotalIncome_New": _resolve_numeric_value(workbook, "IncD.TotalIncome_New", payload, calculation_result),
        "IncD.TotalTaxPayable": _resolve_numeric_value(workbook, "IncD.TotalTaxPayable", payload, calculation_result),
        "IncD.TaxPayableOnRebate": _resolve_numeric_value(workbook, "IncD.TaxPayableOnRebate", payload, calculation_result),
        "IncD.SurchargeOnTaxPayable": _resolve_numeric_value(workbook, "IncD.SurchargeOnTaxPayable", payload, calculation_result),
        "IncD.GrossTaxLiability": _resolve_numeric_value(workbook, "IncD.GrossTaxLiability", payload, calculation_result),
        "IncD.NetTaxLiability": _resolve_numeric_value(workbook, "IncD.NetTaxLiability", payload, calculation_result),
        "IncD.TotTaxPlusIntrstPay": _resolve_numeric_value(workbook, "IncD.TotTaxPlusIntrstPay", payload, calculation_result),
        "IncD.TDS": _resolve_numeric_value(workbook, "IncD.TDS", payload, calculation_result),
        "IncD.TotalTaxesPaid": _resolve_numeric_value(workbook, "IncD.TotalTaxesPaid", payload, calculation_result),
        "IncD.AdvanceTax": 0,
        "IncD.SelfAssessmentTax": 0,
        "IncD.BalTaxPayable": _resolve_numeric_value(workbook, "IncD.BalTaxPayable", payload, calculation_result),
        "IncD.AnyOtherDeductions": 0,
        "IncD.AnyOtherDeductions_Calc": 0,
        "IncD.Deduction16ia": 0,
        "IncD.Deduction16iaa": 0,
        "IncD.Deduction16ic": 0,
        "IncD.GrossRentRecieved": 0,
        "IncD.LessDeduction57": 0,
        "IncD.LessDeduction57New": 0,
        "IncD.Q1Tax": 0,
        "IncD.Q2Tax": 0,
        "IncD.Q3Tax": 0,
        "IncD.Q4Tax": 0,
        "IncD.Q5Tax": 0,
    }

    for name, value in explicit_values.items():
        _set_defined_name(workbook, name, value)


def _zero_fill_unmapped_numeric_fields(workbook) -> int:
    zeroed = 0
    for defined_name in list(workbook.defined_names.keys()):
        if defined_name.startswith("_xleta."):
            continue

        try:
            destinations = list(workbook.defined_names[defined_name].destinations)
        except Exception:
            continue

        if not destinations:
            continue

        sheet_name, cell_ref = destinations[0]
        if not sheet_name or not cell_ref:
            continue

        if sheet_name not in ZERO_FILL_SHEETS:
            continue

        worksheet = workbook[sheet_name]
        target = worksheet[cell_ref]

        # Some defined names point to ranges and openpyxl returns tuples for them.
        # We only zero-fill single-cell names here.
        if isinstance(target, tuple):
            continue

        # Merged follower cells are read-only in openpyxl.
        if isinstance(target, MergedCell):
            continue

        if target.value is None:
            target.value = 0
            zeroed += 1

    return zeroed


def _apply_calculation_settings(workbook) -> None:
    calc = getattr(workbook, "calculation", None)
    if calc is None:
        return

    for attr, value in {
        "calcMode": "auto",
        "forceFullCalc": True,
        "fullCalcOnLoad": True,
    }.items():
        if hasattr(calc, attr):
            setattr(calc, attr, value)


def _find_extraction(session, extraction_id: Optional[str], user_id: Optional[str]) -> Optional[Form16Extraction]:
    query = session.query(Form16Extraction)
    if extraction_id:
        return query.filter(Form16Extraction.extraction_id == extraction_id).first()
    if user_id:
        query = query.filter(Form16Extraction.user_id == user_id)
    return query.order_by(Form16Extraction.created_at.desc()).first()


def populate_itr_xlsm(
    template_path: Path,
    output_path: Path,
    extraction_id: Optional[str] = None,
    user_id: Optional[str] = None,
    fiscal_year: str = DEFAULT_FISCAL_YEAR,
) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        row = _find_extraction(session, extraction_id=extraction_id, user_id=user_id)
        if not row:
            raise RuntimeError("No Form16Extraction row found for the selected filters")

        payload = _extract_row_payload(row)
        inferred_fiscal_year = str(payload.get("financial_year") or fiscal_year or DEFAULT_FISCAL_YEAR)
        calculation = _build_calculation_context(row, inferred_fiscal_year)
        calculation_result = _select_relevant_result(calculation)

        workbook = load_workbook(template_path, keep_vba=True, data_only=False)
        _populate_personal_fields(workbook, payload)
        _populate_calculation_fields(workbook, payload, calculation_result)
        zeroed = _zero_fill_unmapped_numeric_fields(workbook)
        _apply_calculation_settings(workbook)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)

        payload_out = output_path.with_name(output_path.stem + "_payload.json")
        with payload_out.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "extraction_id": row.extraction_id,
                    "assessment_year": "2025-26" if inferred_fiscal_year == "2024-25" else inferred_fiscal_year,
                    "fiscal_year": inferred_fiscal_year,
                    "extracted": {k: (_to_primitive(v) if v is not None else 0) for k, v in payload.items()},
                    "calculation": calculation,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        return {
            "extraction_id": row.extraction_id,
            "template": str(template_path),
            "output_workbook": str(output_path),
            "output_payload": str(payload_out),
            "assessment_year": "2025-26" if inferred_fiscal_year == "2024-25" else inferred_fiscal_year,
            "fiscal_year": inferred_fiscal_year,
            "zero_filled_cells": zeroed,
        }
    finally:
        session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate the ITR xlsm template from DB extraction data")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Path to the ITR xlsm template")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to write the populated workbook")
    parser.add_argument("--extraction-id", default=None, help="Populate from a specific extraction_id")
    parser.add_argument("--user-id", default=None, help="Populate from the latest extraction for this user_id")
    parser.add_argument("--fiscal-year", default=DEFAULT_FISCAL_YEAR, help="Fiscal year to use for tax calculation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = populate_itr_xlsm(
        template_path=Path(args.template),
        output_path=Path(args.output),
        extraction_id=args.extraction_id,
        user_id=args.user_id,
        fiscal_year=args.fiscal_year,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
