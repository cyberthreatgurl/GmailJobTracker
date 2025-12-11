"""General helper utilities for parser.

Extracted from parser.py Phase 4 refactoring for better organization and reusability.
"""


def should_ignore(subject: str, _body: str, patterns: dict) -> bool:
    """Return True if subject/body matches ignore patterns from patterns.json.
    
    Args:
        subject: Email subject line
        _body: Email body (currently unused but kept for API consistency)
        patterns: Dictionary from patterns.json with 'ignore' key
        
    Returns:
        True if message should be ignored, False otherwise
    """
    subj_lower = subject.lower()
    ignore_patterns = patterns.get("ignore", [])
    return any(p.lower() in subj_lower for p in ignore_patterns)


def extract_confidence(result: dict) -> float:
    """Extract confidence score from ML model result.
    
    Handles multiple result formats (confidence key or proba key).
    
    Args:
        result: Dictionary from ML model prediction with confidence/proba
        
    Returns:
        Float confidence score (0.0-1.0), or 0.0 if not available
    """
    if not result:
        return 0.0
    try:
        return float(result.get("confidence", result.get("proba", 0.0)))
    except Exception:
        return 0.0


def log_ignored_message(msg_id: str, metadata: dict, reason: str, ignored_message_model):
    """Upsert IgnoredMessage with reason for auditability and metrics.
    
    Args:
        msg_id: Gmail message ID
        metadata: Message metadata dictionary
        reason: Reason for ignoring (e.g., "spam subject", "no sender")
        ignored_message_model: Django IgnoredMessage model class
        
    Returns:
        Created or updated IgnoredMessage instance
    """
    obj, created = ignored_message_model.objects.update_or_create(
        msg_id=msg_id,
        defaults={
            "subject": metadata.get("subject", ""),
            "sender": metadata.get("sender", ""),
            "reason": reason,
        },
    )
    return obj, created
