#!/usr/bin/env python
"""Check if the Netflix email exists in Gmail and has correct labels."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from gmail_auth import get_gmail_service
from datetime import datetime, timedelta


def check_netflix_email():
    service = get_gmail_service()

    # Search for Netflix email by subject
    query = 'subject:"Engineering Manager, Attack Emulation Team" after:2025/10/20'

    print(f"Searching Gmail for: {query}")
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    print(f"\nFound {len(messages)} messages matching Netflix subject")

    for msg in messages:
        msg_id = msg["id"]
        full_msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        headers = {
            h["name"]: h["value"]
            for h in full_msg.get("payload", {}).get("headers", [])
        }
        subject = headers.get("Subject", "")
        date = headers.get("Date", "")
        sender = headers.get("From", "")

        label_ids = full_msg.get("labelIds", [])

        print(f"\nMessage ID: {msg_id}")
        print(f"Subject: {subject}")
        print(f"Date: {date}")
        print(f"From: {sender}")
        print(f"Label IDs: {label_ids}")

        # Get label names
        labels_resp = service.users().labels().list(userId="me").execute()
        all_labels = labels_resp.get("labels", [])
        id_to_name = {l["id"]: l["name"] for l in all_labels}

        label_names = [id_to_name.get(lid, lid) for lid in label_ids]
        print(f"Label Names: {label_names}")

        # Check if in ProcessedMessage
        from tracker.models import ProcessedMessage

        is_processed = ProcessedMessage.objects.filter(gmail_id=msg_id).exists()
        print(f"Already processed: {is_processed}")

        # Check if it has job-hunt label
        has_jobhunt = any("#job-hunt" in name for name in label_names)
        print(f"Has #job-hunt label: {has_jobhunt}")


if __name__ == "__main__":
    check_netflix_email()
