#!/usr/bin/env python3
"""
Re-ingest all messages sent from USER_EMAIL_ADDRESS via Gmail API.

This script:
1. Fetches all messages from Gmail where sender matches USER_EMAIL_ADDRESS
2. For each message, fetches the raw RFC 2822 format message
3. Runs the message through the ingestion pipeline (parser.ingest_message)
4. Updates existing Message records or creates new ones with correct label and company

Usage:
    python scripts/reingest_user_messages.py
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


def fetch_and_reingest_user_messages():
    """Fetch all messages sent from USER_EMAIL_ADDRESS and re-ingest them."""
    user_email = os.environ.get("USER_EMAIL_ADDRESS", "").strip()

    if not user_email:
        print("❌ ERROR: USER_EMAIL_ADDRESS environment variable not set.")
        return

    print(f"🔍 Fetching all messages sent from: {user_email}")

    # Get Gmail service
    service = get_gmail_service()
    if not service:
        print("❌ ERROR: Could not authenticate with Gmail API.")
        return

    # Build query to find messages sent from user
    query = f"from:{user_email}"

    try:
        # Fetch all message IDs matching the query
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=500,  # Fetch up to 500 messages per page
            )
            .execute()
        )

        messages = results.get("messages", [])
        next_page_token = results.get("nextPageToken")

        # Paginate through all results
        while next_page_token:
            page = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=500, pageToken=next_page_token)
                .execute()
            )
            messages.extend(page.get("messages", []))
            next_page_token = page.get("nextPageToken")

        if not messages:
            print(f"✅ No messages found sent from {user_email}")
            return

        print(f"📧 Found {len(messages)} messages sent from {user_email}")
        print(f"🔄 Beginning re-ingestion...\n")

        ingested = 0
        skipped = 0
        errors = 0

        for i, msg_ref in enumerate(messages, 1):
            msg_id = msg_ref["id"]

            try:
                # Run through ingestion pipeline directly with service and msg_id
                result = ingest_message(service, msg_id)

                if result:
                    ingested += 1
                    print(f"✅ [{i}/{len(messages)}] Ingested message ID: {msg_id}")
                else:
                    skipped += 1
                    print(f"⏭️  [{i}/{len(messages)}] Skipped message ID: {msg_id}")

            except Exception as e:
                errors += 1
                print(
                    f"❌ [{i}/{len(messages)}] Error processing message ID {msg_id}: {e}"
                )

        print(f"\n{'='*60}")
        print(f"📊 Re-ingestion Summary:")
        print(f"   Total messages processed: {len(messages)}")
        print(f"   ✅ Ingested: {ingested}")
        print(f"   ⏭️  Skipped: {skipped}")
        print(f"   ❌ Errors: {errors}")
        print(f"{'='*60}\n")

        # Show sample of re-ingested messages
        print("📋 Sample of user-sent messages after re-ingestion:")
        sample_msgs = Message.objects.filter(sender__icontains=user_email).order_by(
            "-timestamp"
        )[:5]

        for msg in sample_msgs:
            company_name = msg.company.name if msg.company else "None"
            print(f"  • Subject: {msg.subject[:60]}")
            print(
                f"    Label: {msg.ml_label}, Company: {company_name}, Confidence: {msg.confidence:.2f}"
            )

    except Exception as e:
        print(f"❌ ERROR: Failed to fetch messages from Gmail: {e}")


if __name__ == "__main__":
    fetch_and_reingest_user_messages()
