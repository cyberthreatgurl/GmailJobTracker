"""Helper functions and utilities for views.

Extracted from monolithic views.py (Phase 5 refactoring).
Contains shared utilities, validation functions, and helper functions
used across multiple view modules.
"""

import html
import re
from bs4 import BeautifulSoup
from tracker.services import StatsService


def build_sidebar_context():
    """Compute sidebar metrics (companies, applications, weekly trends, upcoming interviews, latest stats).

    Phase 2: Delegates to StatsService for business logic.
    """
    return StatsService.get_sidebar_metrics()


def extract_body_content(raw_html):
    """Return sanitized HTML body if present, otherwise plain-text extracted from the HTML."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script/style/noscript
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Extract body content if present
    body = soup.body
    return str(body) if body else soup.get_text(separator=" ", strip=True)


def validate_regex_pattern(pattern):
    """
    Validate regex pattern for security issues.
    Returns (is_valid, error_message)
    """
    if not pattern or not isinstance(pattern, str):
        return False, "Pattern must be a non-empty string"

    # Length limit to prevent DoS
    if len(pattern) > 500:
        return False, "Pattern too long (max 500 characters)"

    # Check for suspicious patterns that could cause ReDoS
    # (Regular Expression Denial of Service)
    redos_patterns = [
        r"\(\?\#",  # Comment groups can be abused
        r"\(\?\=.*\)\+",  # Nested lookaheads with quantifiers
        r"\(\?\!.*\)\+",  # Nested negative lookaheads
        r"(\(.*\)\+){3,}",  # Multiple nested groups with quantifiers
    ]

    for redos in redos_patterns:
        if re.search(redos, pattern):
            return False, "Pattern contains potentially unsafe construct"

    # Try to compile the regex to ensure it's valid
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex: {str(e)}"

    # Check for extremely complex patterns (complexity check)
    quantifier_count = len(re.findall(r"[*+?{]", pattern))
    if quantifier_count > 20:
        return False, "Pattern too complex (too many quantifiers)"

    return True, None


def sanitize_string(value, max_length=200, allow_regex=False):
    """
    Sanitize user input string for security.
    Returns sanitized string or None if invalid.
    For regex patterns, preserves literal characters (no HTML escaping).
    """
    if not value or not isinstance(value, str):
        return None

    # Remove leading/trailing whitespace
    value = value.strip()

    if not value:
        return None

    # Length check
    if len(value) > max_length:
        return None

    # Block obvious code injection attempts (check before any escaping)
    dangerous_chars = [
        "<script",
        "javascript:",
        "onerror=",
        "onload=",
        "<?php",
        "<%",
        "__import__",
        "eval(",
        "exec(",
    ]
    value_lower = value.lower()
    for danger in dangerous_chars:
        if danger in value_lower:
            return None

    # Block path traversal
    if "../" in value or "..\\" in value or "%2e%2e" in value.lower():
        return None

    # Block null bytes
    if "\x00" in value:
        return None

    # For regex patterns, validate but DON'T html-escape (preserves literal chars)
    if allow_regex:
        is_valid, _error = validate_regex_pattern(value)
        if not is_valid:
            return None
        # Return as-is for JSON storage (template will handle display escaping)
        return value

    # For non-regex strings, HTML escape to prevent XSS
    value = html.escape(value)

    return value


def validate_domain(domain):
    """
    Validate domain name format.
    Returns (is_valid, sanitized_domain)
    """
    if not domain or not isinstance(domain, str):
        return False, None

    domain = domain.strip().lower()

    # Length check
    if len(domain) > 253:
        return False, None

    # Basic domain format check
    # Allow letters, numbers, dots, hyphens
    if not re.match(
        r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
        domain,
    ):
        return False, None

    # Must have at least one dot (TLD)
    if "." not in domain:
        return False, None

    # HTML escape for safety
    domain = html.escape(domain)

    return True, domain


def _parse_pasted_gmail_spec(text: str):
    """Yield dicts like parse_filters() from pasted Gmail spec blocks.

    Recognizes case-insensitive markers:
      - label:
      - Haswords:
      - DoesNotHave:

    Haswords/DoesNotHave may include quoted phrases and | separators; we pass the
    captured strings to sanitize_to_regex_terms downstream.
    """
    current_label = None
    has_buf: list[str] = []
    not_buf: list[str] = []
    lines = text.splitlines()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m_label = re.match(r"(?i)^label\s*:\s*(.+)$", line)
        if m_label:
            # flush previous
            if current_label:
                yield {
                    "label": current_label,
                    "subject": "",
                    "hasTheWord": " | ".join(has_buf).strip(),
                    "doesNotHaveTheWord": " | ".join(not_buf).strip(),
                }
            current_label = m_label.group(1).strip()
            has_buf, not_buf = [], []
            continue
        if re.match(r"(?i)^haswords\s*:\s*", line):
            parts = line.split(":", 1)
            if len(parts) == 2:
                has_buf.append(parts[1].strip())
            continue
        if re.match(r"(?i)^doesnothave\s*:\s*", line):
            parts = line.split(":", 1)
            if len(parts) == 2:
                not_buf.append(parts[1].strip())
            continue
        # Free text lines after a section: treat as additional Haswords
        if current_label:
            has_buf.append(line)
    if current_label:
        yield {
            "label": current_label,
            "subject": "",
            "hasTheWord": " | ".join(has_buf).strip(),
            "doesNotHaveTheWord": " | ".join(not_buf).strip(),
        }


__all__ = [
    "build_sidebar_context",
    "extract_body_content",
    "validate_regex_pattern",
    "sanitize_string",
    "validate_domain",
    "_parse_pasted_gmail_spec",
]
