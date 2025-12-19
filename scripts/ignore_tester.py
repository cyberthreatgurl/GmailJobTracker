"""Test script to validate ignore phrase matching logic."""

import json
from parser import normalize_text, should_ignore

# Load ignore phrases from patterns.json
with open("patterns.json", encoding="utf-8") as f:
    PATTERNS = json.load(f)
IGNORE_PHRASES = [normalize_text(p) for p in PATTERNS.get("ignore", [])]

# Sample subjects to test
TEST_SUBJECTS = [
    "🛎️ Your job alert for: Cybersecurity (IT/OT) Senior Leader, United States",
    "New job opportunities at Viasat!",
    "Your Top Job matches for “Sr. Engineer, Product Abuse - Product Security (Remote)”",
    "Saved job is expiring soon!",
    "Looking for a new job? Check out these roles",
    "Interview Invitation from Acme Corp",
    "Application received for Security Analyst",
]


def test_ignore(subject):
    """Test if a given subject line should be ignored based on configured patterns."""
    result = should_ignore(subject, "")
    normalized = normalize_text(subject)
    matched_phrase = next((p for p in IGNORE_PHRASES if p in normalized), None)
    print(f"Subject: {subject}")
    print(f"→ Ignored: {result}")
    if matched_phrase:
        print(f"→ Matched phrase: {matched_phrase}")
    else:
        print("→ No match found")
    print("-" * 60)


if __name__ == "__main__":
    for subj in TEST_SUBJECTS:
        test_ignore(subj)
