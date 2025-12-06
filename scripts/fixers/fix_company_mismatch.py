#!/usr/bin/env python
"""Fix Application/Message company mismatches.

For each Application, set its company to match the most common company
among the messages in that thread.
"""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from collections import Counter

from tracker.models import Message, ThreadTracking

print("\n" + "=" * 80)
print("FIXING APPLICATION/MESSAGE COMPANY MISMATCHES")
print("=" * 80 + "\n")

fixed_count = 0
skipped_count = 0

# Find all applications
apps = ThreadTracking.objects.all()

for app in apps:
    app_company_id = app.company_id if app.company else None

    # Get all companies from messages in this thread
    message_companies = (
        Message.objects.filter(thread_id=app.thread_id)
        .exclude(company__isnull=True)
        .values_list("company_id", "company__name")
    )

    if not message_companies:
        # No messages with companies, skip
        skipped_count += 1
        continue

    # Count which company appears most in the thread
    company_counts = Counter([c[0] for c in message_companies])
    most_common_company_id = company_counts.most_common(1)[0][0]

    # Get the company name for display
    company_name = next(
        (c[1] for c in message_companies if c[0] == most_common_company_id), "Unknown"
    )

    # Check if there's a mismatch
    if app_company_id != most_common_company_id:
        old_company = app.company.name if app.company else "None"
        print(f"Thread: {app.thread_id}")
        print(f"  OLD: {old_company} (ID: {app_company_id})")
        print(f"  NEW: {company_name} (ID: {most_common_company_id})")
        print(f"  Job: {app.job_title or '(empty)'}")

        # Update the application
        from tracker.models import Company

        app.company = Company.objects.get(id=most_common_company_id)
        app.company_source = "fix_mismatch"
        app.save()

        fixed_count += 1
        print(f"  ✓ Fixed\n")

print("=" * 80)
print(f"SUMMARY:")
print(f"  Fixed: {fixed_count} applications")
print(f"  Skipped: {skipped_count} applications (no message companies)")
print("=" * 80)

if fixed_count > 0:
    print("\n✅ Application companies now match their message threads!")
    print("Run check_company_mismatch.py to verify the fix.")
else:
    print("\n✓ No mismatches found - database is clean!")

