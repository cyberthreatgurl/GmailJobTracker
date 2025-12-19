#!/usr/bin/env python
"""Check the Hampton email company extraction."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

# Find the Hampton email
msg = (
    Message.objects.filter(subject__icontains="Thank You for Applying at Hampton")
    .order_by("-timestamp")
    .first()
)

if msg:
    print("=" * 80)
    print("HAMPTON EMAIL DETAILS")
    print("=" * 80)
    print(f"\nMessage ID: {msg.id}")
    print(f"Gmail ID: {msg.msg_id}")
    print(f"Timestamp: {msg.timestamp}")
    print(f"Subject: {msg.subject}")
    print(f"Sender: {msg.sender}")
    print(f"\nCompany: {msg.company.name if msg.company else 'None'}")
    print(f"Company ID: {msg.company.id if msg.company else 'N/A'}")
    print(f"Company Source: {msg.company_source or 'N/A'}")
    print(f"\nML Label: {msg.ml_label}")
    print(f"Confidence: {msg.confidence}")
    print(f"Reviewed: {msg.reviewed}")

    # Check body for sender info
    print(f"\n" + "=" * 80)
    print("EMAIL BODY (first 500 chars):")
    print("=" * 80)
    print(msg.body[:500] if msg.body else "(no body)")

    # Look for Millennium in body
    if msg.body and "millennium" in msg.body.lower():
        print("\n✓ 'Millennium' found in body")

    # Check sender details
    print(f"\n" + "=" * 80)
    print("SENDER ANALYSIS")
    print("=" * 80)
    sender_parts = msg.sender.split("<")
    if len(sender_parts) > 1:
        display_name = sender_parts[0].strip().strip('"')
        email = sender_parts[1].strip(">")
        print(f"Display Name: {display_name}")
        print(f"Email: {email}")

        if "@" in email:
            email_prefix, domain = email.split("@", 1)
            print(f"Email Prefix: {email_prefix}")
            print(f"Domain: {domain}")
else:
    print("Hampton email not found in database")
