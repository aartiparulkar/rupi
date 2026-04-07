"""LLM-powered tax rule extraction service using LangChain."""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMExtractor:
    """Extract and structure tax rules using LangChain + OpenAI."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=settings.openai_api_key,
            temperature=0,
        )
        self.json_parser = JsonOutputParser()

        self.system_prompt = (
            "You are an expert tax analyst specializing in Indian income tax laws. "
            "Extract tax rules relevant to salaried individuals and return strict JSON only."
        )

    def extract_rules(self, text: str, fiscal_year: str, document_type: str) -> Tuple[List[Dict], float]:
        """Extract tax rules from document text."""
        logger.info(f"Extracting rules from {document_type} for {fiscal_year}")

        try:
            prompt = self._build_extraction_prompt(text, fiscal_year, document_type)
            chain = ChatPromptTemplate.from_messages(
                [
                    ("system", self.system_prompt),
                    ("human", "{prompt}\n\nReturn a JSON array of rule objects only."),
                ]
            ) | self.llm | self.json_parser

            rules_data = chain.invoke({"prompt": prompt})
            if not isinstance(rules_data, list):
                logger.warning("LLM output was not a JSON array")
                return [], 0.0

            rules = self._normalize_rules(rules_data, fiscal_year, document_type)
            confidences = [rule.get("confidence_score", 0.5) for rule in rules]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            logger.info(f"Extracted {len(rules)} rules with avg confidence {avg_confidence:.2f}")
            return rules, avg_confidence
        except Exception as e:
            logger.error(f"Error extracting rules with LLM: {str(e)}", exc_info=True)
            return [], 0.0

    def _build_extraction_prompt(self, text: str, fiscal_year: str, document_type: str) -> str:
        context = {
            "memorandum": "Budget Memorandum with tax changes and announcements.",
            "finance_bill": "Finance Bill with tax law amendments.",
            "budget_highlights": "Summary of key budget highlights.",
        }

        doc_context = context.get(document_type, "Tax policy document.")

        return f"""Extract tax rules relevant to salaried individuals from {document_type} for fiscal year {fiscal_year}.

Context: {doc_context}

For each rule return keys:
- rule_id
- description
- regime (Old Regime/New Regime/Both)
- category (Income, Deductions, Exemptions, Tax Rates, Credits, Penalties, Filing Requirements)
- fiscal_year
- amount
- percentage
- confidence_score (0 to 1)

Document text (first 10000 chars):
{text[:10000]}
"""

    def _normalize_rules(self, rules_data: List[Dict], fiscal_year: str, document_type: str) -> List[Dict]:
        """Normalize and sanitize model output for downstream storage."""
        normalized = []
        doc_prefix = self._get_doc_prefix(document_type)
        fy_prefix = fiscal_year.replace("-", "")

        for i, rule in enumerate(rules_data, 1):
            rule_id = f"RULE_FY{fy_prefix}_{doc_prefix}_{i:03d}"
            confidence = rule.get("confidence_score", 0.75)

            normalized.append(
                {
                    "rule_id": rule_id,
                    "description": rule.get("description"),
                    "regime": rule.get("regime"),
                    "category": rule.get("category"),
                    "fiscal_year": fiscal_year,
                    "amount": self._parse_amount(rule.get("amount")),
                    "percentage": self._parse_percentage(rule.get("percentage")),
                    "confidence_score": max(0, min(1, float(confidence))),
                    "extraction_date": None,
                    "source_document": None,
                }
            )

        return normalized

    def _get_doc_prefix(self, document_type: str) -> str:
        if not document_type:
            return "DOC"
        doc_map = {
            "memorandum": "MEMO",
            "finance_bill": "BILL",
            "budget_highlights": "BUDGET",
        }
        return doc_map.get(document_type.lower(), "DOC")

    def _parse_percentage(self, percentage_value) -> Optional[float]:
        if percentage_value is None:
            return None
        try:
            if isinstance(percentage_value, (int, float)):
                pct = float(percentage_value)
                return pct if 0 <= pct <= 100 else None

            pct_str = str(percentage_value).strip()
            if not pct_str:
                return None

            match = re.search(r"(\d+(?:\.\d{1,2})?)", pct_str)
            if not match:
                return None

            pct = float(match.group(1))
            return pct if 0 <= pct <= 100 else None
        except (ValueError, TypeError):
            logger.warning(f"Could not parse percentage value: {percentage_value}")
            return None

    def _parse_amount(self, amount_value) -> Optional[float]:
        if amount_value is None:
            return None
        try:
            if isinstance(amount_value, (int, float)):
                return float(amount_value)

            amount_str = str(amount_value).strip()
            if not amount_str:
                return None

            amount_str = amount_str.replace("₹", "").replace("$", "").replace(",", "").strip()
            if not amount_str:
                return None

            amount = float(amount_str)
            return amount if amount >= 0 else None
        except (ValueError, TypeError):
            logger.warning(f"Could not parse amount value: {amount_value}")
            return None

    def refine_rule(self, rule: Dict, context: str) -> Dict:
        """Refine an extracted rule using LangChain and return best-effort JSON."""
        try:
            chain = ChatPromptTemplate.from_messages(
                [
                    ("system", "Refine tax rule JSON while preserving factual values."),
                    (
                        "human",
                        "Rule:\n{rule_json}\n\nContext:\n{context}\n\nReturn JSON object only.",
                    ),
                ]
            ) | self.llm

            response = chain.invoke({"rule_json": json.dumps(rule), "context": context[:2000]})
            content = (response.content or "").strip()
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return rule
            return json.loads(match.group(0))
        except Exception as e:
            logger.warning(f"Error refining rule: {str(e)}")
            return rule

    def categorize_rule(self, description: str) -> str:
        """Categorize a rule description using LangChain."""
        categories = [
            "Income",
            "Deductions",
            "Exemptions",
            "Tax Rates",
            "Credits",
            "Penalties",
            "Filing Requirements",
        ]

        try:
            chain = ChatPromptTemplate.from_messages(
                [
                    ("system", "Classify tax rules into one fixed category."),
                    (
                        "human",
                        "Rule: {description}\n\nChoose one: {categories}. Return only the category text.",
                    ),
                ]
            ) | self.llm
            response = chain.invoke({"description": description, "categories": ", ".join(categories)})
            category = (response.content or "").strip()
            return category if category in categories else "Income"
        except Exception as e:
            logger.warning(f"Error categorizing rule: {str(e)}")
            return "Income"


llm_extractor = LLMExtractor()
