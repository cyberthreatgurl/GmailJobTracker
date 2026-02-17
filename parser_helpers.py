"""Shared constants and helper functions extracted from parser.py.

This module eliminates duplication of:
- CANCELLED_PATTERNS (was copy-pasted 3x in parser.py)
- _increment_stat() (was inlined 18x in parser.py)
- _is_headhunter_source() (was inlined 3x in parser.py)

All behavior is identical to the inline originals — this is a pure extraction
with zero logic changes.

Phase 1: Extract constants  (very low risk)
Phase 2: Extract stat helper (very low risk)
Phase 5: Extract headhunter helper (low risk)
"""

import re
import logging

from django.db.models import F
from tracker.models import IngestionStats

logger = logging.getLogger("parser")


# =============================================================================
# Phase 1: Extracted constants
# =============================================================================

# Cancelled position detection patterns — previously duplicated 3x in parser.py.
# These are also defined in json/patterns.json under early_detection.cancelled_position
# but the inline code used a hardcoded superset. This constant captures that superset.
CANCELLED_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r'\b(?:decided|chosen)\s+not\s+to\s+(?:move\s+forward\s+with\s+)?fill(?:ing)?\s+(?:this|the)\s+(?:role|position)\b',
        r'\bevolving\s+business\s+needs\b.*\bnot\s+(?:to\s+)?(?:move\s+forward|proceed|fill)\b',
        r'\bnot\s+(?:to\s+)?move\s+forward\s+with\s+filling\s+(?:this|the)\s+(?:role|position)\b',
        r'\b(?:to\s+)?close\s+(?:the|this)\s+(?:[\w\s]+\s+)?(?:role|position)\s+and\s+not\s+move\s+forward\b',
        r'\b(?:determined|decided)\s+to\s+close\s+(?:the|this)\s+(?:role|position)\b',
        r'\b(?:role|position)\s+(?:has\s+been\s+)?(?:closed|cancelled|canceled)\b',
        r'\bnot\s+(?:to\s+)?(?:move\s+forward|proceed)\s+with\s+(?:filing|filling)\s+(?:this|the)\s+(?:role|position)\b',
        r'\b(?:cancelled|canceled|closed/cancelled|cancelled/closed)\b',
    ]
]


def is_cancelled_position(subject: str, body: str) -> bool:
    """Check if combined subject+body text indicates a cancelled/closed position.

    Uses pre-compiled CANCELLED_PATTERNS for efficient matching.

    Args:
        subject: Email subject line
        body: Email body text

    Returns:
        True if any cancellation pattern matches
    """
    combined = subject + " " + body
    return any(p.search(combined) for p in CANCELLED_PATTERNS)


# =============================================================================
# Phase 2: Extracted stat helper
# =============================================================================

def _increment_stat(stats, field: str) -> None:
    """Atomically increment an IngestionStats counter in DB and in-memory.

    Replaces 18 inlined blocks of:
        IngestionStats.objects.filter(date=stats.date).update(
            <field>=F("<field>") + 1
        )
        if hasattr(stats, "<field>"):
            stats.<field> += 1

    Args:
        stats: IngestionStats instance (from get_stats())
        field: Counter field name (e.g. "total_ignored", "total_inserted",
               "total_skipped")
    """
    IngestionStats.objects.filter(date=stats.date).update(**{field: F(field) + 1})
    if hasattr(stats, field):
        setattr(stats, field, getattr(stats, field) + 1)


# =============================================================================
# Phase 5: Extracted headhunter helper
# =============================================================================

def _is_headhunter_source(
    sender_domain: str,
    company_obj,
    headhunter_domains: set,
    ml_label: str | None = None,
) -> bool:
    """Check if a message originates from a headhunter source.

    Consolidates 3 duplicated blocks in parser.py that computed 4-5 boolean
    variables and OR-ed them together. Each block was ~15 lines.

    Args:
        sender_domain: Lowercase sender email domain
        company_obj: Company model instance (or None)
        headhunter_domains: Set of known headhunter domains
        ml_label: Optional ML classification label (for is_hh_label check)

    Returns:
        True if sender, company domain, company status, or company name
        indicates a headhunter source
    """
    # Check sender domain
    if sender_domain and sender_domain in headhunter_domains:
        return True

    # Check company attributes
    if company_obj:
        company_domain = (getattr(company_obj, "domain", "") or "").strip().lower()
        if company_domain and any(
            company_domain.endswith(d) for d in headhunter_domains
        ):
            return True

        if getattr(company_obj, "status", "") == "headhunter":
            return True

        if (company_obj.name or "").strip().lower() == "headhunter":
            return True

    # Check ML label (used in the application-creation guard)
    if ml_label and ml_label == "head_hunter":
        return True

    return False
