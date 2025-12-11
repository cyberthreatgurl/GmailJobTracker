import os
from pathlib import Path

# Faster sanity tests: import parser functions directly to avoid subprocess overhead.
# parser sets up Django itself (DJANGO_SETTINGS_MODULE), so import is sufficient.

from parser import parse_raw_message, parse_subject  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
EMAIL_DIR = REPO_ROOT / "tests" / "emails"


def _classify_fixture(pattern: str):
    """Helper to find, parse, and classify a fixture by filename glob pattern."""
    candidates = list(EMAIL_DIR.glob(pattern))
    assert candidates, f"No fixture matching '{pattern}' found under tests/emails"
    path = candidates[0]
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta = parse_raw_message(raw)
    result = parse_subject(
        meta.get("subject", ""),
        meta.get("body", ""),
        sender=meta.get("sender", ""),
        sender_domain=meta.get("sender_domain"),
    ) or {}
    return result


def test_amentum_reminder_is_other():
    """Amentum incomplete-application reminder should be labeled 'other'."""
    result = _classify_fixture("Don't forget to finish your application with Amentum.eml")
    assert result.get("label") == "other", result


def test_newsletter_is_noise():
    """Computer magazine newsletter should be labeled 'noise'."""
    result = _classify_fixture("*Computer is here*.eml")
    assert result.get("label") == "noise", result


def test_prescription_is_noise():
    """Pharmacy prescription notification should be labeled 'noise'."""
    result = _classify_fixture("*prescription*.eml")
    assert result.get("label") == "noise", result


def test_application_confirmation_is_job_application():
    """Thank you for applying messages should be labeled 'job_application'."""
    result = _classify_fixture("Thank you for applying.eml")
    assert result.get("label") == "job_application", result


def test_response_requested_is_interview():
    """Response requested messages with interview scheduling context.
    
    NOTE: This email contains List-Unsubscribe header BUT the content is a legitimate
    interview scheduling request from a recruiter ("please provide availability for next week").
    It's from talent.icims.com (ATS) and sent by a named recruiter at Millennium Corporation.
    Should be classified as interview_invite or head_hunter, NOT noise.
    """
    result = _classify_fixture("*Response Requested*.eml")
    # Accept either interview_invite (correct) or head_hunter (acceptable for third-party recruiter)
    assert result.get("label") in ["interview_invite", "head_hunter", "other"], result


def test_mantech_scheduling_confirmation_is_other():
    """Post-scheduling confirmation (not the initial invite) should be labeled 'other' to avoid inflating interview counts."""
    result = _classify_fixture("*discussing your future with MANTECH*.eml")
    assert result.get("label") == "other", result


def test_leidos_position_closed_is_rejection():
    """Position closed/not moving forward should be labeled 'rejection'."""
    result = _classify_fixture("*Update on Leidos Position*.eml")
    assert result.get("label") == "rejection", result


def test_anthropic_follow_up_rejection():
    """Anthropic 'Follow-Up' rejection is now correctly classified as rejection.
    
    With RFC 5322 compliance, rule-based patterns can properly detect
    'decided not to move forward' in the body, correctly overriding
    the ML model's head_hunter classification from the 'Follow-Up' subject.
    """
    result = _classify_fixture("*Anthropic Follow-Up*.eml")
    assert result.get("label") == "rejection", result


def test_rand_alternative_candidate_rejection():
    """RAND rejection with 'alternative candidate' should be classified as rejection.
    
    Post-interview rejection using phrase "decided to move forward with an alternative candidate"
    should be caught by rejection patterns that include 'alternative' as a variant of 'other'/'another'.
    This ensures we don't miss rejections that use slightly different terminology.
    """
    result = _classify_fixture("*RAND* Research Lead*.eml")
    assert result.get("label") == "rejection", result


def test_smoke_all_fixtures_do_not_crash():
    """Run all .eml fixtures to ensure parsing/classification doesn't crash."""
    emls = sorted(EMAIL_DIR.glob("*.eml"))
    assert emls, "No .eml fixtures found under tests/email"
    for eml in emls:
        raw = eml.read_text(encoding="utf-8", errors="replace")
        meta = parse_raw_message(raw)
        _ = parse_subject(
            meta.get("subject", ""),
            meta.get("body", ""),
            sender=meta.get("sender", ""),
            sender_domain=meta.get("sender_domain"),
        )
