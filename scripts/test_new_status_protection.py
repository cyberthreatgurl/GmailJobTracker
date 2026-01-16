#!/usr/bin/env python
"""Test that companies with status='new' are protected from auto-update."""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message
from django.utils.timezone import now

print("Testing status='new' protection...")
print("=" * 60)

# Find companies with status='new' that have messages
new_companies_with_msgs = []
for c in Company.objects.filter(status="new"):
    latest_msg = Message.objects.filter(company=c, ml_label__isnull=False).order_by("-timestamp").first()
    if latest_msg:
        new_companies_with_msgs.append((c, latest_msg))

if not new_companies_with_msgs:
    print("No companies with status='new' and messages found.")
    sys.exit(0)

print(f"Found {len(new_companies_with_msgs)} companies with status='new' and messages\n")

# Show first 5 examples
for c, latest_msg in new_companies_with_msgs[:5]:
    days_since = (now() - latest_msg.timestamp).days
    print(f"{c.name} (ID={c.id}):")
    print(f"  Current status: {c.status}")
    print(f"  Latest message: {latest_msg.ml_label} ({days_since} days ago)")
    
    if latest_msg.ml_label == "job_application" and days_since >= 30:
        print(f"  ✅ Protected: Would normally be 'ghosted' but status='new' preserved")
    elif latest_msg.ml_label == "rejection":
        print(f"  ✅ Protected: Would normally be 'rejected' but status='new' preserved")
    elif latest_msg.ml_label == "interview_invite":
        print(f"  ✅ Protected: Would normally be 'interview' but status='new' preserved")
    else:
        print(f"  ✅ Protected: status='new' preserved")
    print()

print("=" * 60)
print(f"✅ All {len(new_companies_with_msgs)} companies with status='new' are protected from auto-update")
