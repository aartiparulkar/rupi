"""Service for loading and managing tax slabs from JSON configuration"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from models.database import TaxRules

logger = logging.getLogger(__name__)

# Get the config directory path
CONFIG_DIR = Path(__file__).parent.parent / "config"
TAX_SLABS_FILE = CONFIG_DIR / "tax_slabs.json"


class TaxSlabLoader:
    """Load and manage tax slabs and deductions from JSON configuration"""
    
    _slabs_cache = None
    _cache_timestamp = None
    
    @staticmethod
    def _ensure_config_dir():
        """Ensure config directory exists"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def load_slabs() -> Dict:
        """
        Load tax slabs from JSON file
        Uses in-memory cache to avoid repeated file reads
        
        Returns:
            Dictionary with fiscal year tax slab data
        """
        try:
            # Check if cache is still valid (reload every 1 hour)
            now = datetime.now()
            if (TaxSlabLoader._slabs_cache is not None and 
                TaxSlabLoader._cache_timestamp is not None):
                time_diff = (now - TaxSlabLoader._cache_timestamp).total_seconds()
                if time_diff < 3600:  # 1 hour
                    logger.debug("Using cached tax slabs")
                    return TaxSlabLoader._slabs_cache
            
            # Reload from file
            if not TAX_SLABS_FILE.exists():
                logger.error(f"Tax slabs file not found: {TAX_SLABS_FILE}")
                return None
            
            with open(TAX_SLABS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            TaxSlabLoader._slabs_cache = data
            TaxSlabLoader._cache_timestamp = now
            logger.info(f"Loaded tax slabs from {TAX_SLABS_FILE}")
            return data
            
        except Exception as e:
            logger.error(f"Error loading tax slabs: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def get_fiscal_year_slabs(fiscal_year: str, regime: str = "old_regime") -> Optional[Dict]:
        """
        Get tax slabs for a specific fiscal year and regime
        
        Args:
            fiscal_year: Format "2024-25"
            regime: "old_regime" or "new_regime"
        
        Returns:
            Dictionary with slabs list or None if not found
        """
        try:
            slabs_data = TaxSlabLoader.load_slabs()
            if not slabs_data:
                return None
            
            fiscal_data = slabs_data.get("fiscal_years", {}).get(fiscal_year)
            if not fiscal_data:
                logger.warning(f"Fiscal year {fiscal_year} not found, using latest")
                # Fallback to latest available year
                fiscal_years = list(slabs_data.get("fiscal_years", {}).keys())
                if fiscal_years:
                    fiscal_year = sorted(fiscal_years)[-1]
                    fiscal_data = slabs_data["fiscal_years"][fiscal_year]
                else:
                    return None
            
            regime_data = fiscal_data.get("regimes", {}).get(regime)
            return regime_data
            
        except Exception as e:
            logger.error(f"Error getting fiscal year slabs: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def get_slabs_list(fiscal_year: str, regime: str = "old_regime") -> List[Tuple[float, float]]:
        """
        Get tax slabs as list of (max_limit, rate) tuples
        
        Args:
            fiscal_year: Format "2024-25"
            regime: "old_regime" or "new_regime"
        
        Returns:
            List of (limit, rate) tuples for tax calculation
        """
        try:
            regime_data = TaxSlabLoader.get_fiscal_year_slabs(fiscal_year, regime)
            if not regime_data:
                logger.warning(f"Could not find {regime} for {fiscal_year}")
                return []
            
            slabs = regime_data.get("slabs", [])
            result = []
            
            for slab in slabs:
                rate = float(slab.get("rate", 0))
                max_limit = slab.get("max")
                
                if max_limit is None:
                    max_limit = float('inf')
                else:
                    max_limit = float(max_limit)
                
                result.append((max_limit, rate))
            
            logger.debug(f"Loaded {len(result)} slabs for {fiscal_year} {regime}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting slabs list: {str(e)}", exc_info=True)
            return []
    
    @staticmethod
    def get_standard_deduction(fiscal_year: str, regime: str = "old_regime") -> float:
        """
        Get standard deduction for a fiscal year and regime
        
        Args:
            fiscal_year: Format "2024-25"
            regime: "old_regime" or "new_regime"
        
        Returns:
            Standard deduction amount (Old Regime: ₹50,000, New Regime: ₹75,000)
        """
        try:
            regime_data = TaxSlabLoader.get_fiscal_year_slabs(fiscal_year, regime)
            if not regime_data:
                # Default: Old regime ₹50k, New regime ₹75k
                return 50000 if regime == "old_regime" else 75000
            
            standard_deduction = regime_data.get("standard_deduction")
            if standard_deduction is not None:
                return float(standard_deduction)
            
            # Fallback defaults
            return 50000 if regime == "old_regime" else 75000
            
        except Exception as e:
            logger.error(f"Error getting standard deduction: {str(e)}", exc_info=True)
            return 50000 if regime == "old_regime" else 75000
    
    @staticmethod
    def get_health_cess_rate(fiscal_year: str) -> float:
        """Get health and education cess rate for a fiscal year"""
        try:
            slabs_data = TaxSlabLoader.load_slabs()
            if not slabs_data:
                return 0.04  # Default
            
            fiscal_data = slabs_data.get("fiscal_years", {}).get(fiscal_year)
            if not fiscal_data:
                return 0.04
            
            return float(fiscal_data.get("health_cess_rate", 0.04))
            
        except Exception as e:
            logger.error(f"Error getting health cess rate: {str(e)}", exc_info=True)
            return 0.04
    
    @staticmethod
    def get_allowable_deductions(fiscal_year: str, regime: str = "old_regime") -> Dict:
        """Get allowable deductions for old regime"""
        try:
            if regime != "old_regime":
                return {}  # New regime has no deductions
            
            regime_data = TaxSlabLoader.get_fiscal_year_slabs(fiscal_year, regime)
            if not regime_data:
                return {}
            
            return regime_data.get("allowable_deductions", {})
            
        except Exception as e:
            logger.error(f"Error getting allowable deductions: {str(e)}", exc_info=True)
            return {}
    
    @staticmethod
    def update_slabs_from_extracted_rules(fiscal_year: str, db: Session) -> Tuple[bool, str]:
        """
        Use LLM to extract and update tax slabs from stored TaxRules
        This updates the JSON file with rules extracted from government documents
        
        Args:
            fiscal_year: Format "2024-25"
            db: Database session with TaxRules
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Query extracted rules for this fiscal year
            rules = db.query(TaxRules).filter_by(fiscal_year=fiscal_year).all()
            
            if not rules:
                return False, f"No extracted rules found for {fiscal_year}"
            
            logger.info(f"Found {len(rules)} extracted rules for {fiscal_year}")
            
            # Load current slabs
            slabs_data = TaxSlabLoader.load_slabs()
            if not slabs_data:
                return False, "Could not load current tax slabs"
            
            # Extract slab information from rules
            extracted_slabs = TaxSlabLoader._extract_slab_data_from_rules(rules)
            
            if extracted_slabs:
                # Update the slabs for both regimes if we found valid data
                if fiscal_year not in slabs_data.get("fiscal_years", {}):
                    slabs_data["fiscal_years"][fiscal_year] = slabs_data["fiscal_years"]["2025-26"].copy()
                
                # Update with extracted data
                for regime, slab_list in extracted_slabs.items():
                    if regime in slabs_data["fiscal_years"][fiscal_year]["regimes"]:
                        slabs_data["fiscal_years"][fiscal_year]["regimes"][regime]["slabs"] = slab_list
                
                # Save updated slabs
                TaxSlabLoader._ensure_config_dir()
                with open(TAX_SLABS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(slabs_data, f, indent=2, ensure_ascii=False)
                
                # Clear cache to force reload
                TaxSlabLoader._slabs_cache = None
                logger.info(f"Updated tax slabs for {fiscal_year} from extracted rules")
                return True, f"Updated slabs for {fiscal_year}"
            
            return False, "Could not extract slab data from rules"
            
        except Exception as e:
            logger.error(f"Error updating slabs from rules: {str(e)}", exc_info=True)
            return False, f"Error updating slabs: {str(e)}"
    
    @staticmethod
    def _extract_slab_data_from_rules(rules: List[TaxRules]) -> Dict:
        """
        Parse extracted TaxRules to get slab information
        Uses rule descriptions to identify tax slabs
        
        Args:
            rules: List of TaxRules from database
        
        Returns:
            Dictionary with regime-wise slab data
        """
        try:
            extracted_slabs = {"old_regime": [], "new_regime": []}
            
            for rule in rules:
                description = (rule.description or "").lower()
                regime = (rule.regime or "").lower()
                
                # Check if this rule describes a tax slab
                if any(keyword in description for keyword in ["slab", "rate", "tax rate", "bracket"]):
                    # This is a slab rule
                    if "new regime" in regime or "new" in description:
                        slab_entry = TaxSlabLoader._parse_slab_rule(rule, "new_regime")
                        if slab_entry:
                            extracted_slabs["new_regime"].append(slab_entry)
                    elif "old regime" in regime or "old" in description:
                        slab_entry = TaxSlabLoader._parse_slab_rule(rule, "old_regime")
                        if slab_entry:
                            extracted_slabs["old_regime"].append(slab_entry)
            
            # Return only if we found valid slabs
            if extracted_slabs["old_regime"] or extracted_slabs["new_regime"]:
                return {k: v for k, v in extracted_slabs.items() if v}
            
            return {}
            
        except Exception as e:
            logger.error(f"Error extracting slab data: {str(e)}", exc_info=True)
            return {}
    
    @staticmethod
    def _parse_slab_rule(rule: TaxRules, regime: str) -> Optional[Dict]:
        """
        Parse a single tax rule into slab format
        
        Args:
            rule: TaxRules database record
            regime: "old_regime" or "new_regime"
        
        Returns:
            Dictionary with slab data or None
        """
        try:
            # This is a placeholder - actual parsing depends on extracted rule format
            # For now, we return None as extraction logic needs to be refined
            return None
            
        except Exception as e:
            logger.error(f"Error parsing slab rule: {str(e)}", exc_info=True)
            return None
