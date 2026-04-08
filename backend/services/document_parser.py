"""Document parser for user-uploaded tax documents.

Pipeline:
1. Classify document as form_16, salary_slip, or bank_statement.
2. Sanitize sensitive content before storage.
3. Extract tax-calculation fields from Form 16 and salary slips.
"""

import io
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import PyPDF2
try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency guard
    fitz = None
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings
from services.pdf_processor import PDFProcessor

logger = logging.getLogger(__name__)


class DocumentParser:
    """Classify, sanitize, and parse uploaded documents."""

    TAX_FIELDS = {
        "gross_salary",
        "salary_section_17_1",
        "perquisites_17_2",
        "profits_in_lieu_17_3",
        "basic_salary",
        "hra",
        "lta",
        "travel_concession_exemption",
        "gratuity_exemption",
        "commuted_pension_exemption",
        "leave_encashment_exemption",
        "other_section10_exemptions",
        "total_section10_exemptions",
        "salary_after_section10_exemptions",
        "other_allowances",
        "deductions_80c",
        "deductions_80ccc",
        "deductions_80ccd_1",
        "deductions_80ccd_1b",
        "deductions_80ccd_2",
        "deductions_80d",
        "deductions_80e",
        "deductions_other",
        "entertainment_allowance",
        "standard_deduction",
        "professional_tax",
        "total_section16_deductions",
        "income_under_salary",
        "house_property_income",
        "other_sources_income",
        "total_other_income",
        "gross_total_income",
        "chapter_via_total_deductions",
        "tds",
        "net_salary",
        "financial_year",
        "assessment_year",
        "taxable_income",
        "tax_payable",
        "net_payable_tax",
        "surcharge",
        "health_education_cess",
        "relief_89",
        "section_87a_rebate",
        "house_rent_exemption_10_13a",
        "donations_80g",
        "other_income",
        "form16_part_a_present",
        "form16_part_b_present",
    }

    CLASSIFICATION_KEYWORDS = {
        "form_16": [
            "form no. 16",
            "certificate under section 203",
            "part a",
            "part b",
            "tan of deductor",
            "pan of deductee",
            "assessment year",
        ],
        "salary_slip": [
            "salary slip",
            "payslip",
            "earnings",
            "deductions",
            "net pay",
            "employee id",
            "gross earnings",
        ],
        "bank_statement": [
            "bank statement",
            "account number",
            "ifsc",
            "opening balance",
            "closing balance",
            "debit",
            "credit",
            "transaction",
        ],
    }

    PATTERNS = {
        "gross_salary": [
            r"(?:gross\s+salary|total\s+gross|gross\s+earnings)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"(?:salary\s+as\s+per\s+sec(?:tion)?\s*17)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"(?:1\.\s*gross\s+salary|1\s+gross\s+salary)[^\n]*\n(?:.*\n){0,3}?\(d\)\s*total\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "salary_section_17_1": [
            r"salary\s+as\s+per\s+provision\s+contained\s+in\s+section\s+17\(1\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "perquisites_17_2": [
            r"value\s+of\s+perquisites\s+under\s+section\s+17\(2\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "profits_in_lieu_17_3": [
            r"profit\s+in\s+lieu\s+of\s+salary\s+under\s+section\s+17\(3\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "basic_salary": [
            r"(?:basic\s+(?:salary|pay)?)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "hra": [
            r"(?:house\s+rent\s+allowance|hra)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "lta": [
            r"(?:leave\s+travel\s+(?:concession|allowance)|lta|ltc)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "travel_concession_exemption": [
            r"travel\s+concession\s+or\s+assisstance\s+under\s+section\s+10[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "gratuity_exemption": [
            r"death-cum-retirement\s+gratuity\s+under\s+section\s+10[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "commuted_pension_exemption": [
            r"commuted\s+value\s+of\s+pension\s+under\s+section\s+10\(10a\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "leave_encashment_exemption": [
            r"leave\s+salary\s+encashment\s+under\s+section\s+10\(10aa\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "other_section10_exemptions": [
            r"amount\s+of\s+any\s+other\s+exempt(?:ion)?\s+under\s+section\s+10[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "total_section10_exemptions": [
            r"total\s+amount\s+of\s+any\s+other\s+exemption\s+under\s+section[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "salary_after_section10_exemptions": [
            r"total\s+amount\s+of\s+salary\s+received\s+from\s+current\s+employer[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80c": [
            r"(?:80\s*c|section\s*80\s*c)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80ccc": [
            r"section\s*80\s*ccc[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80ccd_1": [
            r"section\s*80\s*ccd\(1\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80ccd_1b": [
            r"section\s*80\s*ccd\(1b\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80ccd_2": [
            r"section\s*80\s*ccd\(2\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80d": [
            r"(?:80\s*d|section\s*80\s*d|health\s+insurance)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "standard_deduction": [
            r"(?:standard\s+deduction)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "entertainment_allowance": [
            r"entertainment\s+allowance\s+under\s+section\s+16\(ii\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "professional_tax": [
            r"(?:professional\s+tax|pt)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"tax\s+on\s+employment\s+under\s+section\s+16\(iii\)[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "total_section16_deductions": [
            r"total\s+amount\s+of\s+deduction\s+under\s+section\s+16(?:\(ia\))?[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "income_under_salary": [
            r"income\s+chargeable\s+under\s+the\s+head\s+\"salaries\"[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "house_property_income": [
            r"income\s+from\s+house\s+property\s+reported\s+by\s+employee[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "other_sources_income": [
            r"income\s+under\s+the\s+head\s+other\s+sources\s+offered\s+by\s+tds[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "total_other_income": [
            r"total\s+amount\s+of\s+other\s+income\s+reported\s+by\s+the\s+employee[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "gross_total_income": [
            r"gross\s+total\s+income\s*\(6\+8\)\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"gross\s+total\s+income\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "chapter_via_total_deductions": [
            r"aggregate\s+of\s+deductible\s+amount\s+under\s+chapter\s+vi-a[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "tds": [
            r"(?:^|\n)\s*(?:tds|tax\s+deducted\s+at\s+source)\b[^\n]*?[:\-₹]\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"amount\s+of\s+tax\s+deducted\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "net_salary": [
            r"(?:net\s+(?:salary|pay)|take\s+home)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "financial_year": [
            r"(?:financial\s+year|fy)\s*[:\-]?\s*([0-9]{4}[-–][0-9]{2,4})",
        ],
        "assessment_year": [
            r"(?:assessment\s+year|ay)\s*[:\-]?\s*([0-9]{4}[-–][0-9]{2,4})",
        ],
        "taxable_income": [
            r"(?:total\s+taxable\s+income|taxable\s+income)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "tax_payable": [
            r"(?:tax\s+payable|net\s+payable\s+tax)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"tax\s+payable\s*\(13\+15\+16-14\)\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "net_payable_tax": [
            r"net\s+payable\s+tax\s*\(17-18\)\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"net\s+payable\s+tax\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "surcharge": [
            r"surcharge,?\s+wherever\s+applicable\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"surcharge\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "health_education_cess": [
            r"health\s+and\s+education\s+cess\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"health\s+and\s+education\s+cess\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "relief_89": [
            r"relief\s+under\s+section\s+89[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "section_87a_rebate": [
            r"(?:rebate\s+under\s+section\s*87a)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "house_rent_exemption_10_13a": [
            r"(?:house\s+rent\s+allowance\s+under\s+section\s*10\(13a\))\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"(?:section\s*10\(13a\))\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "donations_80g": [
            r"(?:section\s*80g|donations?)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "other_income": [
            r"(?:income\s+under\s+the\s+head\s+other\s+sources)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
    }

    SENSITIVE_PATTERNS = {
        "aadhar": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
        "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE),
        "tan": re.compile(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", re.IGNORECASE),
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "employer_name_field": re.compile(
            r"\b(?:name\s+of\s+)?employer\s+name\b\s*[:\-#]?\s*([A-Za-z][A-Za-z0-9&.,'()\-/\s]{1,120})",
            re.IGNORECASE,
        ),
        "employee_name_field": re.compile(
            r"\b(?:name\s+of\s+)?employee\s+name\b\s*[:\-#]?\s*([A-Za-z][A-Za-z0-9&.,'()\-/\s]{1,120})",
            re.IGNORECASE,
        ),
        "ifsc": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.IGNORECASE),
        "bank_account_inline": re.compile(
            r"\b(?:account(?:\s*(?:number|no\.?))?|a/c|ac(?:count)?\s*no\.?)\b\s*[:\-#]?\s*([0-9]{9,18})",
            re.IGNORECASE,
        ),
        "mobile": re.compile(r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b"),
        "signature_url": re.compile(r"https?://[^\s]+(?:sign|signature)[^\s]*", re.IGNORECASE),
        "address_line": re.compile(
            r"\b(?:address|addr)\b\s*[:\-]?.*", re.IGNORECASE
        ),
    }

    def __init__(self):
        self.pdf_processor = PDFProcessor()
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key,
            temperature=0,
        )

    @staticmethod
    def _parse_amount(raw: str) -> Optional[float]:
        try:
            return float(raw.replace(",", ""))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _is_plausible_amount(raw: str, amount: Optional[float], context_line: str = "") -> bool:
        """Filter out serial numbers/section numbers commonly mis-read as monetary amounts."""
        if amount is None:
            return False

        cleaned = (raw or "").strip()
        line = (context_line or "").lower()
        if amount == 0:
            return True
        if amount >= 100:
            return True

        # Amount-like formatting usually indicates a real value.
        if any(token in cleaned for token in [",", "."]) or "₹" in line or "rs" in line:
            return True

        # Small integers on lines mentioning sections are usually section numbers.
        if "section" in line or re.search(r"\b\d+\([a-z0-9]+\)", line):
            return False

        return False

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Redact sensitive identifiers and address-like lines from extracted text."""
        if not text:
            return ""

        sanitized = text
        sanitized = cls.SENSITIVE_PATTERNS["aadhar"].sub("[REDACTED_AADHAR]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["pan"].sub("[REDACTED_PAN]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["tan"].sub("[REDACTED_TAN]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["email"].sub("[REDACTED_EMAIL]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["employer_name_field"].sub(
            lambda m: re.sub(r"(?i)(?:name\s+of\s+)?employer\s+name\b\s*[:\-#]?\s*.*", "Employer Name: [REDACTED_NAME]", m.group(0)),
            sanitized,
        )
        sanitized = cls.SENSITIVE_PATTERNS["employee_name_field"].sub(
            lambda m: re.sub(r"(?i)(?:name\s+of\s+)?employee\s+name\b\s*[:\-#]?\s*.*", "Employee Name: [REDACTED_NAME]", m.group(0)),
            sanitized,
        )
        sanitized = cls.SENSITIVE_PATTERNS["ifsc"].sub("[REDACTED_IFSC]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["mobile"].sub("[REDACTED_MOBILE]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["bank_account_inline"].sub(
            lambda m: m.group(0).replace(m.group(1), "[REDACTED_ACCOUNT]"),
            sanitized,
        )
        sanitized = cls.SENSITIVE_PATTERNS["signature_url"].sub("[REDACTED_SIGNATURE_URL]", sanitized)
        sanitized = cls.SENSITIVE_PATTERNS["address_line"].sub("Address: [REDACTED]", sanitized)
        return sanitized

    @classmethod
    def classify_document(cls, filename: str, text: str) -> str:
        """Classify document into form_16, salary_slip, or bank_statement."""
        corpus = f"{filename}\n{text[:5000]}".lower()
        scores = {"form_16": 0, "salary_slip": 0, "bank_statement": 0}

        for doc_type, keywords in cls.CLASSIFICATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in corpus:
                    scores[doc_type] += 1

        best_type = max(scores, key=scores.get)
        return best_type if scores[best_type] > 0 else "salary_slip"

    @classmethod
    def _collect_sensitive_literals(cls, text: str) -> List[str]:
        """Collect exact sensitive strings for deterministic PDF redaction."""
        if not text:
            return []

        literals = set()
        direct_keys = ["aadhar", "pan", "tan", "email", "employer_name_field", "employee_name_field", "ifsc", "mobile"]
        for key in direct_keys:
            for match in cls.SENSITIVE_PATTERNS[key].finditer(text):
                token = (match.group(0) or "").strip()
                if token:
                    literals.add(token)

        for match in cls.SENSITIVE_PATTERNS["bank_account_inline"].finditer(text):
            account_number = (match.group(1) or "").strip()
            if account_number:
                literals.add(account_number)

        return sorted(literals, key=len, reverse=True)

    @staticmethod
    def _strip_pdf_metadata(file_content: bytes) -> bytes:
        """Remove PDF metadata while preserving original page content."""
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            writer = PyPDF2.PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.add_metadata({})
            output = io.BytesIO()
            writer.write(output)
            return output.getvalue()
        except Exception as exc:
            logger.warning(f"PDF metadata sanitization failed, using original bytes: {exc}")
            return file_content

    @classmethod
    def _sanitize_pdf_bytes(cls, file_content: bytes) -> bytes:
        """Redact sensitive text in digital PDFs and strip metadata before storage."""
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            extracted_text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            logger.warning(f"PDF text extraction failed during sanitization: {exc}")
            return cls._strip_pdf_metadata(file_content)

        literals = cls._collect_sensitive_literals(extracted_text)
        if not literals:
            return cls._strip_pdf_metadata(file_content)

        if fitz is None:
            logger.warning("PyMuPDF is not installed; using metadata-only PDF sanitization")
            return cls._strip_pdf_metadata(file_content)

        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            total_hits = 0

            for page in doc:
                page_hits = 0
                for literal in literals:
                    for rect in page.search_for(literal):
                        page.add_redact_annot(rect, text="[REDACTED]", fill=(0, 0, 0))
                        page_hits += 1
                if page_hits:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                    total_hits += page_hits

            if total_hits == 0:
                doc.close()
                return cls._strip_pdf_metadata(file_content)

            doc.set_metadata({})
            redacted_bytes = doc.tobytes(garbage=4, deflate=True)
            doc.close()
            return redacted_bytes
        except Exception as exc:
            logger.warning(f"PDF content redaction failed, using metadata-only sanitization: {exc}")
            return cls._strip_pdf_metadata(file_content)

    def sanitize_for_storage(self, file_content: bytes, filename: str) -> bytes:
        """Sanitize upload bytes before storing in Supabase."""
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            return self._sanitize_pdf_bytes(file_content)
        return file_content

    @staticmethod
    def build_sanitized_storage_payload(
        original_filename: str,
        classified_type: str,
        sanitized_text: str,
        tax_data: Dict,
    ) -> Tuple[bytes, str]:
        """Build a sanitized JSON payload for storage in Supabase."""
        payload = {
            "original_filename": original_filename,
            "classified_document_type": classified_type,
            "sanitized_text": sanitized_text,
            "tax_data": tax_data,
        }
        storage_filename = f"sanitized_{Path(original_filename).stem}.json"
        return json.dumps(payload, ensure_ascii=True).encode("utf-8"), storage_filename

    @classmethod
    def extract_with_regex(cls, text: str) -> Dict:
        """Extract tax fields with deterministic regex rules."""
        result = {}
        text_lower = text.lower()
        for field, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if not match:
                    continue
                raw = match.group(1).strip()
                if field in ("financial_year", "assessment_year"):
                    result[field] = raw
                else:
                    amount = cls._parse_amount(raw)
                    if cls._is_plausible_amount(raw, amount, match.group(0)):
                        result[field] = amount
                break
        return result

    @staticmethod
    def extract_with_langchain_loader(file_path: str) -> str:
        """Extract PDF text with LangChain PyPDFLoader for better page-aware context."""
        try:
            loader = PyPDFLoader(file_path)
            docs = loader.load()
            return "\n".join(doc.page_content for doc in docs if doc.page_content)
        except Exception as exc:
            logger.warning(f"PyPDFLoader extraction failed: {exc}")
            return ""

    @classmethod
    def extract_form16_table_fields(cls, text: str) -> Dict:
        """Extract fields from Form-16 style tabular text blocks."""
        if not text:
            return {}

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        lowered = [ln.lower() for ln in lines]
        result: Dict = {}

        result["form16_part_a_present"] = any("part a" in ln for ln in lowered)
        result["form16_part_b_present"] = any("part b" in ln for ln in lowered)

        table_map = {
            "salary_section_17_1": ["salary as per provision contained in section 17(1)"],
            "perquisites_17_2": ["value of perquisites under section 17(2)"],
            "profits_in_lieu_17_3": ["profit in lieu of salary under section 17(3)"],
            "house_rent_exemption_10_13a": ["house rent allowance under section 10(13a)", "10(13a)"],
            "travel_concession_exemption": ["travel concession or assisstance under section 10"],
            "gratuity_exemption": ["death-cum-retirement gratuity under section 10"],
            "commuted_pension_exemption": ["commuted value of pension under section 10(10a)"],
            "leave_encashment_exemption": ["leave salary encashment under section 10(10aa)", "cash equipement of leave salary encashment"],
            "other_section10_exemptions": ["amount of any other exempt on under section 10", "amount of any other exemption under section 10"],
            "total_section10_exemptions": ["total amount of any other exemption under section", "total amount of any other exemption under section 10"],
            "salary_after_section10_exemptions": ["total amount of salary received from current employer"],
            "standard_deduction": ["standard deduction under section 16(ia)", "standard deduction"],
            "entertainment_allowance": ["entertainment allowance under section 16(ii)"],
            "professional_tax": ["tax on employment under section 16(iii)"],
            "total_section16_deductions": ["total amount of deduction under section 16"],
            "income_under_salary": ["income chargeable under the head \"salaries\""],
            "house_property_income": ["income from house property reported by employee offered for tds"],
            "other_sources_income": ["income under the head other sources offered by tds"],
            "total_other_income": ["total amount of other income reported by the employee"],
            "gross_total_income": ["gross total income (6+8)", "gross total income"],
            "deductions_80c": ["under section 80c", "life insurance premia"],
            "deductions_80ccc": ["section 80ccc"],
            "deductions_80ccd_1": ["section 80ccd(1)"],
            "deductions_80ccd_1b": ["section 80ccd(1b)", "notified pension scheme under section 80ccd(1b)"],
            "deductions_80ccd_2": ["section 80ccd(2)", "contribution by employer to pension scheme"],
            "deductions_80d": ["under section 80d", "health insurance"],
            "deductions_80e": ["under section 80e", "higher education"],
            "chapter_via_total_deductions": ["aggregate of deductible amount under chapter vi-a"],
            "donations_80g": ["under section 80g", "donations"],
            "taxable_income": ["total taxable income", "total taxable"],
            "tax_payable": ["net payable tax", "tax payable"],
            "net_payable_tax": ["net payable tax (17-18)", "net payable tax"],
            "surcharge": ["surcharge, wherever applicable", "surcharge"],
            "health_education_cess": ["health and education cess"],
            "relief_89": ["relief under section 89"],
            "section_87a_rebate": ["rebate under section 87a"],
            "tds": ["amount of tax deducted", "amount of tax deposited"],
            "gross_salary": ["gross salary", "salary as per provision contained in section 17"],
        }

        def parse_amount_from_line(value_line: str) -> Optional[float]:
            # Remove section references and serial prefixes that often look numeric but are not monetary values.
            scrubbed = re.sub(r"section\s*\d+[a-z]?(?:\([a-z0-9]+\))*", " ", value_line, flags=re.IGNORECASE)
            scrubbed = re.sub(r"\b\d+\([a-z0-9]+\)", " ", scrubbed, flags=re.IGNORECASE)
            scrubbed = re.sub(r"^\s*\d+\.?\s*", " ", scrubbed)

            amount_matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d)", scrubbed)
            if not amount_matches:
                return None

            for raw in reversed(amount_matches):
                try:
                    amount = float(raw.replace(",", ""))
                except ValueError:
                    continue
                if cls._is_plausible_amount(raw, amount, value_line):
                    return amount
            return None

        for idx, line in enumerate(lowered):
            for field, keys in table_map.items():
                if field in result and result[field] is not None:
                    continue
                if any(k in line for k in keys):
                    window = lines[idx: min(idx + 3, len(lines))]
                    amount = None
                    for probe in window:
                        amount = parse_amount_from_line(probe)
                        if amount is not None:
                            break
                    if amount is not None:
                        result[field] = amount

        return result

    def extract_with_llm(self, text: str, document_type: str) -> Dict:
        """Use LangChain/OpenAI to enrich tax field extraction."""
        if not self._llm:
            return {}

        try:
            parser = JsonOutputParser()
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "Extract only tax-calculation fields for Indian salaried taxpayers and return strict JSON.",
                    ),
                    (
                        "human",
                        "Document type: {document_type}\n\nText:\n{text}\n\n"
                        "Return JSON with keys: gross_salary, salary_section_17_1, perquisites_17_2, profits_in_lieu_17_3, "
                        "basic_salary, hra, lta, travel_concession_exemption, gratuity_exemption, commuted_pension_exemption, "
                        "leave_encashment_exemption, other_section10_exemptions, total_section10_exemptions, "
                        "salary_after_section10_exemptions, deductions_80c, deductions_80ccc, deductions_80ccd_1, "
                        "deductions_80ccd_1b, deductions_80ccd_2, deductions_80d, deductions_80e, deductions_other, "
                        "standard_deduction, entertainment_allowance, professional_tax, total_section16_deductions, "
                        "income_under_salary, house_property_income, other_sources_income, total_other_income, "
                        "gross_total_income, chapter_via_total_deductions, taxable_income, tax_payable, net_payable_tax, "
                        "surcharge, health_education_cess, relief_89, section_87a_rebate, donations_80g, tds, net_salary, "
                        "financial_year, assessment_year. "
                        "Use null when unknown.",
                    ),
                ]
            )
            chain = prompt | self._llm | parser
            extracted = chain.invoke({"document_type": document_type, "text": text[:10000]})
            if not isinstance(extracted, dict):
                return {}

            cleaned = {}
            for key, value in extracted.items():
                if key not in self.TAX_FIELDS or value is None:
                    continue
                if key in ("financial_year", "assessment_year"):
                    cleaned[key] = str(value)
                else:
                    try:
                        cleaned[key] = float(str(value).replace(",", ""))
                    except (TypeError, ValueError):
                        continue
            return cleaned
        except Exception as exc:
            logger.warning(f"LLM extraction failed, falling back to regex: {exc}")
            return {}

    @classmethod
    def _filter_tax_fields(cls, data: Dict) -> Dict:
        return {k: v for k, v in data.items() if k in cls.TAX_FIELDS and v is not None}

    @classmethod
    def extract_identity_fields(cls, text: str) -> Dict:
        """Extract identity fields from raw document text before sanitization."""
        if not text:
            return {}

        identity: Dict[str, str] = {}
        normalized_text = text.replace("\r\n", "\n")

        label_patterns = {
            "employee_name": [
                r"(?:name\s+of\s+)?employee\s+name\s*[:\-#]?\s*([A-Za-z][A-Za-z .,'()&\-/]{1,120})",
                r"(?:employee|employee\s*:)\s*([A-Za-z][A-Za-z .,'()&\-/]{1,120})",
            ],
            "employer_name": [
                r"(?:name\s+of\s+)?employer\s+name\s*[:\-#]?\s*([A-Za-z][A-Za-z0-9 .,'()&\-/]{1,160})",
                r"(?:employer|deductor|company)\s*name\s*[:\-#]?\s*([A-Za-z][A-Za-z0-9 .,'()&\-/]{1,160})",
            ],
            "address": [
                r"(?:residential\s+)?address\s*[:\-#]?\s*([^\n]{4,200})(?:\n|$)",
                r"(?:present\s+)?address\s*[:\-#]?\s*([^\n]{4,200})(?:\n|$)",
            ],
        }

        for field_name, patterns in label_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE)
                if not match:
                    continue
                value = re.sub(r"\s+", " ", match.group(1)).strip(" ,;:-")
                if value:
                    identity[field_name] = value
                    break

        pan_match = cls.SENSITIVE_PATTERNS["pan"].search(normalized_text)
        if pan_match:
            pan_value = pan_match.group(0).upper()
            identity["pan"] = pan_value
            identity["pan_last4"] = pan_value[-4:]

        if identity.get("address"):
            identity["address"] = identity["address"].rstrip(" .,")

        return identity

    def extract_financial_data(self, file_path: str, document_type: str) -> Tuple[Dict, Optional[str], str]:
        """Extract tax fields from uploaded file path and return (data, error, sanitized_text)."""
        try:
            raw_text = self.pdf_processor.extract_text(file_path, use_llm_cleanup=True)
            langchain_text = self.extract_with_langchain_loader(file_path)
            if len(langchain_text) > len(raw_text):
                raw_text = langchain_text
            if not raw_text.strip():
                return {}, "Could not extract text from document", ""

            sanitized_text = self.sanitize_text(raw_text)
            regex_data = self.extract_with_regex(sanitized_text)
            llm_data = self.extract_with_llm(sanitized_text, document_type)
            form16_table_data = self.extract_form16_table_fields(sanitized_text) if document_type == "form_16" else {}

            merged = {**regex_data, **form16_table_data, **llm_data}
            filtered = self._filter_tax_fields(merged)

            if "gross_salary" not in filtered and filtered.get("net_salary") and filtered.get("tds"):
                filtered["gross_salary"] = filtered["net_salary"] + filtered["tds"]

            return filtered, None, sanitized_text
        except Exception as exc:
            logger.error(f"Document parsing failed: {exc}", exc_info=True)
            return {}, f"Parsing failed: {exc}", ""

    def extract_from_bytes(
        self,
        file_content: bytes,
        filename: str,
        document_type: Optional[str] = None,
    ) -> Tuple[Dict, Optional[str], str, str, Dict]:
        """Classify and extract tax fields from bytes.

        Returns:
            (extracted_tax_data, error, classified_type, sanitized_text_preview, identity_fields)
        """
        ext = Path(filename).suffix.lower() or ".pdf"
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            raw_text = self.pdf_processor.extract_text(tmp_path, use_llm_cleanup=True)
            identity_fields = self.extract_identity_fields(raw_text)
            sanitized_text = self.sanitize_text(raw_text)
            classified_type = document_type or self.classify_document(filename, sanitized_text)

            if classified_type in {"form_16", "salary_slip"}:
                data, error, _ = self.extract_financial_data(tmp_path, classified_type)
                return data, error, classified_type, sanitized_text, identity_fields

            return {}, None, classified_type, sanitized_text, identity_fields
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


# Singleton instance
document_parser = DocumentParser()
