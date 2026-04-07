"""
LLM-based utility to intelligently extract and populate tax slabs from documents
Uses OpenAI to parse extracted tax rules and update the JSON configuration
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session
from models.database import TaxRules
import openai
from app.config import settings

logger = logging.getLogger(__name__)

# Get the config directory path
CONFIG_DIR = Path(__file__).parent.parent / "config"
TAX_SLABS_FILE = CONFIG_DIR / "tax_slabs.json"


class TaxSlabLLMExtractor:
    """Use LLM to extract tax slab information from extracted rules"""
    
    @staticmethod
    def extract_slabs_from_rules(fiscal_year: str, db: Session) -> Tuple[bool, Dict, str]:
        """
        Use OpenAI to analyze extracted tax rules and determine tax slabs
        
        Args:
            fiscal_year: Fiscal year in format "2024-25"
            db: Database session
        
        Returns:
            Tuple of (success, slab_data, message)
            where slab_data contains {"old_regime": [...], "new_regime": [...]}
        """
        try:
            # Query extracted rules for this fiscal year
            rules = db.query(TaxRules).filter_by(fiscal_year=fiscal_year).all()
            
            if not rules:
                return False, {}, f"No extracted rules found for {fiscal_year}"
            
            # Prepare rules summary for LLM
            rules_text = TaxSlabLLMExtractor._prepare_rules_for_llm(rules)
            
            logger.info(f"Sending {len(rules)} rules to LLM for slab extraction")
            
            # Call OpenAI to extract slabs
            slab_data = TaxSlabLLMExtractor._call_llm_for_extraction(fiscal_year, rules_text)
            
            if slab_data:
                return True, slab_data, f"Successfully extracted slabs for {fiscal_year}"
            else:
                return False, {}, "LLM could not extract valid slab data"
            
        except Exception as e:
            logger.error(f"Error extracting slabs with LLM: {str(e)}", exc_info=True)
            return False, {}, f"Error: {str(e)}"
    
    @staticmethod
    def _prepare_rules_for_llm(rules: List[TaxRules]) -> str:
        """
        Prepare extracted rules as text for LLM processing
        Focuses on rules related to tax slabs and rates
        """
        try:
            text_parts = []
            
            for rule in rules:
                # Focus on rules mentioning slabs, rates, brackets
                if any(keyword in (rule.description.lower() if rule.description else "")
                       for keyword in ["slab", "rate", "bracket", "tax rate", "income", "percentage"]):
                    text_parts.append(f"""
Rule: {rule.description}
Regime: {rule.regime}
Category: {rule.category}
Amount: {rule.amount}
Percentage: {rule.percentage}
""")
            
            return "\n".join(text_parts) if text_parts else ""
            
        except Exception as e:
            logger.error(f"Error preparing rules for LLM: {str(e)}", exc_info=True)
            return ""
    
    @staticmethod
    def _call_llm_for_extraction(fiscal_year: str, rules_text: str) -> Optional[Dict]:
        """
        Call OpenAI GPT to extract tax slabs and deductions from rule text
        
        Args:
            fiscal_year: Fiscal year string
            rules_text: Extracted rules as text
        
        Returns:
            Dictionary with old_regime and new_regime slab data or None
        """
        try:
            # Set OpenAI API key
            openai.api_key = settings.openai_api_key
            
            prompt = f"""
You are a tax expert. Analyze the following extracted tax rules for fiscal year {fiscal_year} and extract:
1. Old Regime Tax Slabs: List each tax slab with min income, max income, and tax rate
2. New Regime Tax Slabs: List each tax slab with min income, max income, and tax rate
3. Standard Deduction for Old Regime
4. Health & Education Cess Rate (usually 4%)

Extracted Rules:
{rules_text}

Format your response as valid JSON with this exact structure:
{{
  "old_regime": {{
    "slabs": [
      {{"min": 0, "max": 250000, "rate": 0.0, "description": "Up to 2.5 lakhs"}},
      {{"min": 250000, "max": 500000, "rate": 0.05, "description": "2.5-5 lakhs"}}
    ],
    "standard_deduction": 50000,
    "deductions": {{"section_80c": {{"max": 150000}}, "section_80d": {{"max": 25000}}}}
  }},
  "new_regime": {{
    "slabs": [
      {{"min": 0, "max": 300000, "rate": 0.0, "description": "Up to 3 lakhs"}},
      {{"min": 300000, "max": 600000, "rate": 0.05, "description": "3-6 lakhs"}}
    ]
  }},
  "health_cess_rate": 0.04
}}

Return ONLY the JSON, no other text.
"""
            
            logger.info("Calling OpenAI API to extract tax slabs...")
            
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a tax expert who extracts tax slab information. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Low temperature for consistency
                max_tokens=2000
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            slab_data = json.loads(response_text)
            
            logger.info(f"Successfully extracted slab data from LLM")
            return slab_data
            
        except json.JSONDecodeError as e:
            logger.error(f"LLM response was not valid JSON: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error calling LLM for extraction: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def update_json_with_llm_data(fiscal_year: str, slab_data: Dict) -> Tuple[bool, str]:
        """
        Update the tax_slabs.json file with data extracted by LLM
        
        Args:
            fiscal_year: Fiscal year string
            slab_data: Slab data from LLM with old_regime and new_regime
        
        Returns:
            Tuple of (success, message)
        """
        try:
            # Load existing slabs
            if TAX_SLABS_FILE.exists():
                with open(TAX_SLABS_FILE, 'r', encoding='utf-8') as f:
                    slabs_json = json.load(f)
            else:
                slabs_json = {"metadata": {}, "fiscal_years": {}}
            
            # Ensure fiscal year entry exists
            if fiscal_year not in slabs_json.get("fiscal_years", {}):
                slabs_json["fiscal_years"][fiscal_year] = {
                    "assessment_year": f"{int(fiscal_year.split('-')[0])+1}-{int(fiscal_year.split('-')[1])+1}",
                    "standard_deduction": 50000,
                    "health_cess_rate": 0.04,
                    "regimes": {}
                }
            
            # Update with LLM-extracted data
            if "old_regime" in slab_data:
                old_regime_data = slab_data["old_regime"]
                slabs_json["fiscal_years"][fiscal_year]["regimes"]["old_regime"] = {
                    "name": "Old Tax Regime",
                    "description": "Traditional regime with exemptions and deductions",
                    "slabs": old_regime_data.get("slabs", []),
                    "allowable_deductions": old_regime_data.get("deductions", {})
                }
                
                if "standard_deduction" in old_regime_data:
                    slabs_json["fiscal_years"][fiscal_year]["standard_deduction"] = old_regime_data["standard_deduction"]
            
            if "new_regime" in slab_data:
                new_regime_data = slab_data["new_regime"]
                slabs_json["fiscal_years"][fiscal_year]["regimes"]["new_regime"] = {
                    "name": "New Tax Regime",
                    "description": "Simplified regime with lower rates but no deductions",
                    "slabs": new_regime_data.get("slabs", [])
                }
            
            if "health_cess_rate" in slab_data:
                slabs_json["fiscal_years"][fiscal_year]["health_cess_rate"] = slab_data["health_cess_rate"]
            
            # Save updated JSON
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(TAX_SLABS_FILE, 'w', encoding='utf-8') as f:
                json.dump(slabs_json, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Updated tax slabs JSON with LLM-extracted data for {fiscal_year}")
            return True, f"Successfully updated tax slabs for {fiscal_year}"
            
        except Exception as e:
            logger.error(f"Error updating JSON with LLM data: {str(e)}", exc_info=True)
            return False, f"Error updating JSON: {str(e)}"
    
    @staticmethod
    def smart_update_fiscal_year(fiscal_year: str, db: Session) -> Tuple[bool, str]:
        """
        Smart update: Extract rules → Call LLM → Update JSON
        End-to-end pipeline for fiscal year slabs
        
        Args:
            fiscal_year: Fiscal year in format "2024-25"
            db: Database session
        
        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info(f"Starting smart LLM-based update for {fiscal_year}...")
            
            # Step 1: Extract slabs from rules
            success, slab_data, message = TaxSlabLLMExtractor.extract_slabs_from_rules(fiscal_year, db)
            
            if not success:
                logger.warning(f"Failed to extract slabs: {message}")
                return False, message
            
            # Step 2: Update JSON with extracted data
            success, msg = TaxSlabLLMExtractor.update_json_with_llm_data(fiscal_year, slab_data)
            
            if success:
                logger.info(f"Successfully updated {fiscal_year} slabs via LLM")
                return True, f"Successfully processed {fiscal_year}: {msg}"
            else:
                return False, msg
                
        except Exception as e:
            logger.error(f"Error in smart update: {str(e)}", exc_info=True)
            return False, f"Error: {str(e)}"
