"""Fix user replies to personal email addresses that were incorrectly labeled as 'other'.

This script finds user reply/forward messages sent to personal domains (gmail.com,
yahoo.com, etc.) that were incorrectly labeled as 'other' instead of 'noise'.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
from gmail_auth import get_gmail_service
from parser import ingest_message


def fix_personal_replies():
    """Find and fix user replies to personal domains."""
    user_email = os.environ.get("USER_EMAIL_ADDRESS", "").strip().lower()
    if not user_email:
        print("❌ USER_EMAIL_ADDRESS not set in environment")
        return

    print(f"🔍 Finding user replies to personal domains labeled as 'other'...")

    # Personal email domains
    personal_domains = [
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "aol.com",
        "icloud.com",
    ]

    # Find user-sent messages with label='other'
    user_messages = Message.objects.filter(
        sender__icontains=user_email, ml_label="other"
    ).order_by("-timestamp")

    print(f"📊 Found {user_messages.count()} user-sent 'other' messages")

    # Filter to replies/forwards only
    replies_forwards = [
        msg
        for msg in user_messages
        if msg.subject and msg.subject.lower().startswith(("re:", "fwd:", "fw:"))
    ]

    print(f"🎯 Found {len(replies_forwards)} user replies/forwards")

    # Now check which are to personal domains by parsing the body for "To:" or checking recipients
    # For simplicity, we'll use heuristics: if body contains personal domain email addresses
    candidates = []
    for msg in replies_forwards:
        body_lower = (msg.body or "").lower()
        # Check if body contains personal email addresses
        if any(f"@{domain}" in body_lower for domain in personal_domains):
            candidates.append(msg)
            # Show a preview
            if len(candidates) <= 10:
                print(f"  - {msg.subject[:60]} | {msg.timestamp.strftime('%Y-%m-%d')}")

    print(f"\n📝 Found {len(candidates)} candidates (replies to personal domains)")

    if not candidates:
        print("✅ No personal reply candidates found")
        return

    proceed = input(
        f"\n⚠️  Proceed with re-ingesting {len(candidates)} messages? (yes/no): "
    )
    if proceed.lower() not in ("yes", "y"):
        print("❌ Aborted by user")
        return

    # Get Gmail service
    service = get_gmail_service()
    if not service:
        print("❌ Failed to initialize Gmail service")
        return

    print(f"\n🔄 Re-ingesting {len(candidates)} messages...")
    restored = 0
    skipped = 0
    errors = 0

    for i, msg in enumerate(candidates, 1):
        try:
            # Re-ingest the message - parser.py will now detect personal domain replies
            ingest_message(service, msg.msg_id)

            # Refresh from DB to see new label
            msg.refresh_from_db()

            if msg.ml_label == "noise":
                restored += 1
                print(
                    f"✅ [{i}/{len(candidates)}] Restored: {msg.subject[:50]} -> Label: {msg.ml_label}"
                )
            else:
                skipped += 1
                print(
                    f"⏭️  [{i}/{len(candidates)}] Kept: {msg.subject[:50]} -> Label: {msg.ml_label}"
                )

        except Exception as e:
            errors += 1
            print(f"❌ [{i}/{len(candidates)}] Error for {msg.msg_id}: {e}")

    print(f"\n📊 Restoration Summary:")
    print(f"   Total processed: {len(candidates)}")
    print(f"   ✅ Restored to noise: {restored}")
    print(f"   ⏭️  Kept as other: {skipped}")
    print(f"   ❌ Errors: {errors}")


if __name__ == "__main__":
    fix_personal_replies()
