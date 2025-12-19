#!/usr/bin/env python3
"""
Restore original labels for user replies/forwards that were incorrectly labeled as 'other'.

This script:
1. Finds all messages sent by USER_EMAIL_ADDRESS with label='other' and confidence=1.0
2. Filters to only replies/forwards (subject starts with Re:, Fwd:, Fw:)
3. Re-ingests these messages to restore correct ML-based labels

Usage:
    python scripts/restore_reply_labels.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from gmail_auth import get_gmail_service
from parser import ingest_message
from tracker.models import Message


def restore_reply_labels():
    """Find and re-ingest user replies/forwards that were incorrectly labeled as 'other'."""
    user_email = os.environ.get("USER_EMAIL_ADDRESS", "").strip()

    if not user_email:
        print("❌ ERROR: USER_EMAIL_ADDRESS environment variable not set.")
        return

    print(f"🔍 Finding user replies/forwards incorrectly labeled as 'other'...")

    # Find all user-sent messages with label='other' and confidence=1.0 (from incorrect re-ingest)
    user_messages = Message.objects.filter(
        sender__icontains=user_email, ml_label="other", confidence=1.0
    )

    # Filter to only replies/forwards
    replies_forwards = [
        msg
        for msg in user_messages
        if msg.subject and msg.subject.lower().startswith(("re:", "fwd:", "fw:"))
    ]

    print(
        f"📧 Found {len(replies_forwards)} user replies/forwards with incorrect 'other' label"
    )

    if not replies_forwards:
        print("✅ No messages to restore.")
        return

    print(f"🔄 Re-ingesting to restore correct labels...\n")

    # Get Gmail service
    service = get_gmail_service()
    if not service:
        print("❌ ERROR: Could not authenticate with Gmail API.")
        return

    restored = 0
    skipped = 0
    errors = 0

    for i, msg in enumerate(replies_forwards, 1):
        try:
            # Re-ingest the message
            result = ingest_message(service, msg.msg_id)

            if result:
                restored += 1
                # Refresh from DB to get updated label
                msg.refresh_from_db()
                print(
                    f"✅ [{i}/{len(replies_forwards)}] Restored: {msg.subject[:60]} -> Label: {msg.ml_label}"
                )
            else:
                skipped += 1
                print(f"⏭️  [{i}/{len(replies_forwards)}] Skipped: {msg.subject[:60]}")

        except Exception as e:
            errors += 1
            print(f"❌ [{i}/{len(replies_forwards)}] Error restoring {msg.msg_id}: {e}")

    print(f"\n{'='*60}")
    print(f"📊 Restoration Summary:")
    print(f"   Total processed: {len(replies_forwards)}")
    print(f"   ✅ Restored: {restored}")
    print(f"   ⏭️  Skipped: {skipped}")
    print(f"   ❌ Errors: {errors}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    restore_reply_labels()
