#!/usr/bin/env python
"""Verify that ghosted applications don't appear in interview queries."""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking

print("\n" + "=" * 80)
print("INTERVIEW QUERY TEST")
print("=" * 80 + "\n")

# Old query (includes ghosted)
old_query = ThreadTracking.objects.filter(
    interview_date__isnull=False, company__isnull=False
).exclude(ml_label="noise")

print(f"OLD QUERY (includes ghosted): {old_query.count()} applications")
guidehouse_old = old_query.filter(company_id=38)
print(f"  → Guidehouse Federal: {guidehouse_old.count()} applications")
if guidehouse_old.exists():
    for app in guidehouse_old:
        print(f"    - Status: {app.status}, Interview: {app.interview_date}")

print()

# New query (excludes ghosted)
new_query = (
    ThreadTracking.objects.filter(interview_date__isnull=False, company__isnull=False)
    .exclude(ml_label="noise")
    .exclude(status="ghosted")
    .exclude(status="rejected")
    .exclude(rejection_date__isnull=False)
)

print(f"NEW QUERY (excludes ghosted/rejected): {new_query.count()} applications")
guidehouse_new = new_query.filter(company_id=38)
print(f"  → Guidehouse Federal: {guidehouse_new.count()} applications")
if guidehouse_new.exists():
    for app in guidehouse_new:
        print(f"    - Status: {app.status}, Interview: {app.interview_date}")
else:
    print(f"    ✓ Correctly excluded from Interviews With box")

print("\n" + "=" * 80)
print("RESULT:")
print("=" * 80)
if guidehouse_new.count() == 0 and guidehouse_old.count() > 0:
    print("✅ Fix successful! Guidehouse Federal no longer appears in interview query")
else:
    print("⚠️  Check results above")

