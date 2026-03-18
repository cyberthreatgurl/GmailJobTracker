import re

def normalize_company_name(name: str) -> str:
    """
    Normalize company name by stripping common legal suffixes and punctuation.
    Used for fuzzy matching and API searches.

    Args:
        name: Raw company name (e.g. "Acme Corp, Inc.")

    Returns:
        Normalized name (e.g. "Acme")
    """
    if not name:
        return ""

    # 1. Lowercase
    norm = name.lower()

    # 2. Remove common legal suffixes
    # We use \b to ensure we match whole words
    suffixes = [
        r"\bllc\b", r"\binc\b", r"\bcorp\b", r"\bcorporation\b",
        r"\bco\b", r"\bltd\b", r"\blimited\b", r"\bcompany\b",
        r"\bincorporated\b", r"\bholdings\b", r"\bgroup\b",
        r"\btechnologies\b", r"\btechnology\b", r"\bsolutions\b",
        r"\bsystems\b", r"\bservices\b", r"\bllp\b", r"\bpllc\b",
        r"\bgmbh\b", r"\bsa\b", r"\bplc\b"
    ]

    # Combine patterns for efficiency
    pattern = "|".join(suffixes)
    norm = re.sub(pattern, "", norm)

    # 3. Remove punctuation and extra whitespace
    norm = re.sub(r"[^\w\s]", " ", norm)

    # 4. Collapse whitespace
    norm = re.sub(r"\s+", " ", norm).strip()

    # Check if we stripped everything (e.g. if company name was just "Solutions Inc")
    # If so, revert to original (cleaned up)
    if not norm:
        return re.sub(r"\s+", " ", name.strip())

    return norm
