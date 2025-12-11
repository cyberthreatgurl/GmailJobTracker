"""
Company name validation and normalization utilities.

Extracted from parser.py as part of Phase 1 refactoring.
"""
import re
from typing import Optional


class CompanyValidator:
    """Handles company name validation and normalization.
    
    This class provides methods for:
    - Validating company names against invalid patterns
    - Normalizing company names (removing artifacts, standardizing format)
    - Detecting if a string looks like a person's name rather than a company
    """
    
    def __init__(self, patterns: dict):
        """Initialize the validator with pattern definitions.
        
        Args:
            patterns: Dictionary containing 'invalid_company_prefixes' and other patterns
        """
        self.patterns = patterns
        self.invalid_prefixes = patterns.get("invalid_company_prefixes", [])
    
    def is_valid_company_name(self, name: Optional[str]) -> bool:
        """Reject company names that match known invalid prefixes from patterns.
        
        Args:
            name: Company name to validate
            
        Returns:
            True if valid company name, False if invalid or matches exclusion patterns
        """
        if not name:
            return False

        for prefix in self.invalid_prefixes:
            try:
                # Compile each prefix as regex, using re.IGNORECASE
                if re.match(prefix, name, re.IGNORECASE):
                    return False
            except re.error:
                # If invalid regex, fallback to simple startswith
                if name.lower().startswith(prefix.lower()):
                    return False
        return True
    
    def normalize_company_name(self, name: str) -> str:
        """Normalize common subject-derived artifacts from company names.

        - Strip whitespace and trailing punctuation
        - Remove suffix fragments like "- Application ..." or trailing "Application"
        - Collapse repeated whitespace
        - Map known pseudo-companies like "Indeed Application" -> "Indeed"
        
        Args:
            name: Company name to normalize
            
        Returns:
            Normalized company name
        """
        if not name:
            return ""

        n = name.strip()

        # Remove common subject suffixes accidentally captured
        n = re.sub(r"\s*-\s*Application.*$", "", n, flags=re.IGNORECASE)
        n = re.sub(r"\bApplication\b\s*$", "", n, flags=re.IGNORECASE)

        # Trim lingering separators/punctuation
        n = re.sub(r"[\s\-:|•]+$", "", n)

        # Collapse multiple internal spaces
        n = re.sub(r"\s{2,}", " ", n)

        # Known normalizations
        lower = n.lower()
        if lower == "indeed application":
            return "Indeed"

        return n
    
    def looks_like_person(self, name: str) -> bool:
        """Heuristic: return True if the string looks like an individual person's name.

        Criteria (intentionally conservative so we *reject* obvious person names):
        - 1–3 tokens, each starting with capital then lowercase letters only
        - No token contains digits, '&', '@', '.', or corporate suffix markers
        - Contains no common company suffix words (Inc, LLC, Corp, Company, Technologies, Systems)
        - If exactly two tokens and both are common first/last name shapes (<=12 chars) treat as person
        
        Args:
            name: Name string to check
            
        Returns:
            True if likely a person name, False if likely a company name
        """
        if not name:
            return False
        raw = name.strip()
        if len(raw) > 40:  # Long strings unlikely to be just a person name
            return False
        tokens = raw.split()
        if not (1 <= len(tokens) <= 3):
            return False
        corp_markers = {
            "inc", "llc", "ltd", "co", "corp", "corporation", 
            "company", "technologies", "systems", "group"
        }
        if any(t.lower().strip(".,") in corp_markers for t in tokens):
            return False
        # Reject if any token has non alpha (besides hyphen) or is ALLCAPS acronym
        for t in tokens:
            if not re.match(r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)?$", t):
                return False
        # Two-token typical person pattern
        if len(tokens) == 2 and all(len(t) <= 12 for t in tokens):
            return True
        # Single short token like "Kelly" should not be considered a company unless in known companies
        if len(tokens) == 1 and len(tokens[0]) <= 10:
            return True
        return False
