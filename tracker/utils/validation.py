"""Company name validation and normalization utilities.

Extracted from parser.py Phase 4 refactoring for better organization and reusability.
"""


def is_valid_company_name(name: str, company_validator) -> bool:
    """Reject company names that match known invalid prefixes from patterns.json.
    
    Args:
        name: Company name to validate
        company_validator: CompanyValidator instance with patterns
        
    Returns:
        True if valid company name, False if invalid or matches exclusion patterns
    """
    return company_validator.is_valid_company_name(name)


def normalize_company_name(name: str, company_validator) -> str:
    """Normalize common subject-derived artifacts from company names.

    - Strip whitespace and trailing punctuation
    - Remove suffix fragments like "- Application ..." or trailing "Application"
    - Collapse repeated whitespace
    - Map known pseudo-companies like "Indeed Application" -> "Indeed"
    
    Args:
        name: Company name to normalize
        company_validator: CompanyValidator instance
        
    Returns:
        Normalized company name
    """
    return company_validator.normalize_company_name(name)


def looks_like_person(name: str, company_validator) -> bool:
    """Heuristic: return True if the string looks like an individual person's name.

    Criteria (intentionally conservative so we *reject* obvious person names):
    - 1–3 tokens, each starting with capital then lowercase letters only
    - No token contains digits, '&', '@', '.', or corporate suffix markers
    - Contains no common company suffix words (Inc, LLC, Corp, Company, Technologies, Systems)
    - If exactly two tokens and both are common first/last name shapes (<=12 chars) treat as person
    
    Args:
        name: Name string to check
        company_validator: CompanyValidator instance
        
    Returns:
        True if likely a person name, False if likely a company name
    """
    return company_validator.looks_like_person(name)
