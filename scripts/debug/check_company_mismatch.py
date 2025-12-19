#!/usr/bin/env python
"""Check for Application/Message company mismatch."""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()


from tracker.models import Message, ThreadTracking

print("\n" + "=" * 80)
print("APPLICATION vs MESSAGE COMPANY MISMATCH CHECK")
print("=" * 80 + "\n")

# Find all applications
apps = ThreadTracking.objects.all()
mismatches = []

for app in apps:
    app_company_id = app.company_id if app.company else None
    app_company_name = app.company.name if app.company else "None"

    # Get messages in this thread
    messages = Message.objects.filter(thread_id=app.thread_id)

    # Check what companies the messages point to
    message_companies = (
        messages.exclude(company__isnull=True)
        .values_list("company_id", "company__name")
        .distinct()
    )

    if message_companies:
        # Check if app company matches any message company
        message_company_ids = set([c[0] for c in message_companies])

        if app_company_id not in message_company_ids:
            mismatches.append(
                {
                    "thread_id": app.thread_id,
                    "app_company_id": app_company_id,
                    "app_company_name": app_company_name,
                    "message_companies": list(message_companies),
                    "job_title": app.job_title or "(empty)",
                    "sent_date": app.sent_date,
                }
            )

print(f"Found {len(mismatches)} applications with company mismatches\n")

for i, m in enumerate(mismatches[:20], 1):
    print(f"{i}. Thread: {m['thread_id']}")
    print(
        f"   Application company: {m['app_company_name']} (ID: {m['app_company_id']})"
    )
    print(
        f"   Message companies: {', '.join([f'{name} (ID: {cid})' for cid, name in m['message_companies']])}"
    )
    print(f"   Job: {m['job_title']}")
    print(f"   Date: {m['sent_date']}")
    print()

if len(mismatches) > 20:
    print(f"... and {len(mismatches) - 20} more mismatches")

print("\n" + "=" * 80)
print("DIAGNOSIS:")
print("=" * 80)
print("Application.company should match the company of messages in that thread.")
print("This mismatch suggests a bug in the ingestion logic where Application.company")
print("is set to a different company than the messages in the thread.")
