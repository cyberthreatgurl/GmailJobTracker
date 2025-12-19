"""
Safe cleanup script to re-ingest likely newsletter messages.

This script identifies messages that are probably newsletters based on:
- Known newsletter sender domains
- List-Unsubscribe headers
- Newsletter-like subjects
- Bulk mail characteristics

It then re-ingests them, allowing the updated header hint logic to properly
move them to IgnoredMessage table and delete them from Message table.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, IgnoredMessage
from parser import ingest_message
from gmail_auth import get_gmail_service
import re


# Known newsletter domains (safe to re-ingest)
NEWSLETTER_DOMAINS = [
    "ieee.org",
    "deliver.ieee.org",
    "acm.org",
    "stackoverflow.email",
    "github.com",
    "gitlab.com",
    "medium.com",
    "substack.com",
    "linkedin.com",
    "indeed.com",  # Job alert newsletters
    "dice.com",
    "glassdoor.com",
    "monster.com",
    "clearancejobs.com",
    "newsletter",  # Generic newsletter in domain
    "news.",  # news.company.com patterns
    "noreply",
    "no-reply",
    "donotreply",
]

# Newsletter subject patterns
NEWSLETTER_PATTERNS = [
    r"\bissue\s+of\b",  # "November 2025 issue of"
    r"\bnewsletter\b",
    r"\bdigest\b",
    r"\bdaily\s+brief\b",
    r"\bweekly\s+roundup\b",
    r"\btop\s+stories\b",
    r"\bjob\s+alert\b",
    r"\bjobs?\s+matching\b",
    r"\brecommended\s+for\s+you\b",
    r"\byour\s+weekly\b",
    r"\byour\s+daily\b",
]


def is_likely_newsletter(msg):
    """Check if a message is likely a newsletter based on multiple signals."""
    score = 0
    reasons = []

    # Check sender domain
    sender_lower = msg.sender.lower()
    for domain in NEWSLETTER_DOMAINS:
        if domain in sender_lower:
            score += 2
            reasons.append(f"newsletter domain: {domain}")
            break

    # Check subject patterns
    subject_lower = msg.subject.lower()
    for pattern in NEWSLETTER_PATTERNS:
        if re.search(pattern, subject_lower, re.IGNORECASE):
            score += 3
            reasons.append(f"subject pattern: {pattern}")
            break

    # Check if already marked as noise (but not reviewed)
    if msg.ml_label == "noise" and not msg.reviewed:
        score += 1
        reasons.append("ML labeled as noise")

    # Check low confidence (suggests uncertain classification)
    if msg.confidence < 0.7:
        score += 1
        reasons.append(f"low confidence: {msg.confidence:.2f}")

    # Require at least score of 3 to be considered likely newsletter
    is_newsletter = score >= 3

    return is_newsletter, score, reasons


def find_likely_newsletters(dry_run=True):
    """Find and optionally re-ingest likely newsletter messages."""

    print("=" * 80)
    print("Newsletter Cleanup Script")
    print("=" * 80)
    print()

    # Find messages that might be newsletters
    messages = Message.objects.all().select_related("company")

    likely_newsletters = []
    for msg in messages:
        is_newsletter, score, reasons = is_likely_newsletter(msg)
        if is_newsletter:
            likely_newsletters.append((msg, score, reasons))

    print(
        f"Found {len(likely_newsletters)} likely newsletter messages out of {messages.count()} total"
    )
    print()

    if not likely_newsletters:
        print("✓ No likely newsletters found! Your Message table looks clean.")
        return

    # Sort by score (highest confidence first)
    likely_newsletters.sort(key=lambda x: x[1], reverse=True)

    # Show top candidates
    print("Top 10 Newsletter Candidates:")
    print("-" * 80)
    for i, (msg, score, reasons) in enumerate(likely_newsletters[:10], 1):
        print(f"{i}. [{score} points] {msg.subject[:60]}")
        print(f"   From: {msg.sender}")
        print(f"   Reasons: {', '.join(reasons)}")
        print()

    if dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No changes made")
        print("=" * 80)
        print()
        print(f"To actually clean up these {len(likely_newsletters)} messages, run:")
        print(f"  python scripts/cleanup_newsletters.py --execute")
        print()
        print("This will:")
        print("  1. Re-ingest each message")
        print("  2. Let header hint logic detect newsletters")
        print("  3. Delete from Message table")
        print("  4. Add to IgnoredMessage table")
        return

    # Execute cleanup
    print("=" * 80)
    print("EXECUTING CLEANUP")
    print("=" * 80)
    print()

    service = get_gmail_service()
    success_count = 0
    error_count = 0
    deleted_count = 0

    for i, (msg, score, reasons) in enumerate(likely_newsletters, 1):
        try:
            msg_id = msg.msg_id
            print(
                f"[{i}/{len(likely_newsletters)}] Re-ingesting: {msg.subject[:50]}..."
            )

            # Check if it exists before re-ingesting
            exists_before = Message.objects.filter(msg_id=msg_id).exists()

            # Re-ingest (will trigger auto-ignore logic)
            result = ingest_message(service, msg_id)

            # Check if it was deleted
            exists_after = Message.objects.filter(msg_id=msg_id).exists()

            if exists_before and not exists_after:
                deleted_count += 1
                print(f"  ✓ Deleted from Message table (result: {result})")
            elif result == "ignored":
                print(f"  ✓ Marked as ignored")
            else:
                print(f"  ℹ Still in Message table (result: {result})")

            success_count += 1

        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1

    print()
    print("=" * 80)
    print("CLEANUP COMPLETE")
    print("=" * 80)
    print(f"Successfully processed: {success_count}")
    print(f"Deleted from Message:   {deleted_count}")
    print(f"Errors:                 {error_count}")
    print()

    # Show remaining newsletters
    remaining = sum(
        1
        for msg, _, _ in likely_newsletters
        if Message.objects.filter(msg_id=msg.msg_id).exists()
    )
    print(f"Remaining likely newsletters: {remaining}")

    if remaining > 0:
        print()
        print("Note: Some messages may still be in Message table because:")
        print("  - They matched application-related patterns in patterns.json")
        print("  - Header hints didn't detect them as newsletters")
        print("  - They are legitimate job tracking messages")


if __name__ == "__main__":
    import sys

    # Check for --execute flag
    execute = "--execute" in sys.argv

    if execute:
        response = input(
            "⚠️  This will re-ingest likely newsletter messages. Continue? (yes/no): "
        )
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    find_likely_newsletters(dry_run=not execute)
