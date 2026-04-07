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
        "basic_salary",
        "hra",
        "lta",
        "other_allowances",
        "deductions_80c",
        "deductions_80d",
        "deductions_80e",
        "deductions_other",
        "standard_deduction",
        "professional_tax",
        "tds",
        "net_salary",
        "financial_year",
        "assessment_year",
        "taxable_income",
        "tax_payable",
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
        "deductions_80c": [
            r"(?:80\s*c|section\s*80\s*c)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "deductions_80d": [
            r"(?:80\s*d|section\s*80\s*d|health\s+insurance)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "standard_deduction": [
            r"(?:standard\s+deduction)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "professional_tax": [
            r"(?:professional\s+tax|pt)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ],
        "tds": [
            r"(?:tds|tax\s+deducted\s+at\s+source)\s*[:\-₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
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
        "aadhar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
        "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE),
        "tan": re.compile(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", re.IGNORECASE),
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
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

    @staticmethod
    def _sanitize_pdf_bytes(file_content: bytes) -> bytes:
        """Remove PDF metadata before storage."""
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
                    if amount is not None:
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
            "house_rent_exemption_10_13a": ["house rent allowance under section 10(13a)", "10(13a)"],
            "standard_deduction": ["standard deduction under section 16(ia)", "standard deduction"],
            "deductions_80c": ["under section 80c", "life insurance premia"],
            "deductions_80d": ["under section 80d", "health insurance"],
            "deductions_80e": ["under section 80e", "higher education"],
            "donations_80g": ["under section 80g", "donations"],
            "taxable_income": ["total taxable income", "total taxable"],
            "tax_payable": ["net payable tax", "tax payable"],
            "section_87a_rebate": ["rebate under section 87a"],
            "tds": ["tax deducted at source", "amount of tax deducted"],
            "gross_salary": ["gross salary", "salary as per provision contained in section 17"],
        }

        def parse_amount_from_line(value_line: str) -> Optional[float]:
            amount_matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d)", value_line)
            if not amount_matches:
                return None
            raw = amount_matches[-1]
            try:
                return float(raw.replace(",", ""))
            except ValueError:
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
                        "Return JSON with keys: gross_salary, basic_salary, hra, lta, other_allowances, "
                        "deductions_80c, deductions_80d, deductions_80e, deductions_other, standard_deduction, "
                        "professional_tax, tds, net_salary, financial_year, assessment_year. "
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
    ) -> Tuple[Dict, Optional[str], str, str]:
        """Classify and extract tax fields from bytes.

        Returns:
            (extracted_tax_data, error, classified_type, sanitized_text_preview)
        """
        ext = Path(filename).suffix.lower() or ".pdf"
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            raw_text = self.pdf_processor.extract_text(tmp_path, use_llm_cleanup=True)
            sanitized_text = self.sanitize_text(raw_text)
            classified_type = document_type or self.classify_document(filename, sanitized_text)

            if classified_type in {"form_16", "salary_slip"}:
                data, error, _ = self.extract_financial_data(tmp_path, classified_type)
                return data, error, classified_type, sanitized_text

            return {}, None, classified_type, sanitized_text
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


# Singleton instance
document_parser = DocumentParser()
