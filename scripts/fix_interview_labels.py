#!/usr/bin/env python
"""
Fix mislabeled interview messages in the last week.
Run with: python fix_interview_labels.py
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.utils.timezone import now
from datetime import timedelta
from tracker.models import Message

print("=" * 80)
print("FIXING MISLABELED INTERVIEW MESSAGES")
print("=" * 80)

# Get interview messages from last 7 days
interviews = Message.objects.filter(
    ml_label="interview_invite",
    timestamp__gte=now() - timedelta(days=7),
    company__isnull=False,
).order_by("-timestamp")

print(
    f"\nFound {interviews.count()} messages labeled as 'interview_invite' in last 7 days:\n"
)

fixes = []

for i, msg in enumerate(interviews, 1):
    print(f"{i}. {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.company.name}")
    print(f"   Subject: {msg.subject}")
    print(f"   Sender: {msg.sender}")

    # Pattern matching for mislabeled messages
    suggested_label = None
    reason = ""

    # Check for Indeed application confirmations
    if "indeed application:" in msg.subject.lower():
        suggested_label = "job_application"
        reason = "Indeed application confirmation (not interview)"

    # Check for "Thank You for Applying"
    elif "thank you for applying" in msg.subject.lower():
        suggested_label = "job_application"
        reason = "Application confirmation (not interview)"

    # Check for news/spam keywords
    elif any(
        kw in msg.subject.lower()
        for kw in ["trump", "panics", "airports", "government"]
    ):
        suggested_label = "noise"
        reason = "News/spam content (not job-related)"

    # Likely real interview - contains interview/schedule keywords
    elif any(
        kw in msg.subject.lower() for kw in ["interview with", "schedule", "calendly"]
    ):
        suggested_label = "interview_invite"  # Keep as is
        reason = "Appears to be genuine interview invitation"

    if suggested_label and suggested_label != msg.ml_label:
        print(f"   → SUGGESTED FIX: Change to '{suggested_label}' ({reason})")
        fixes.append(
            {
                "msg": msg,
                "old_label": msg.ml_label,
                "new_label": suggested_label,
                "reason": reason,
            }
        )
    else:
        print(f"   ✓ Label appears correct")

    print()

if fixes:
    print("=" * 80)
    print(f"PROPOSED CHANGES: {len(fixes)} messages need relabeling")
    print("=" * 80)

    for fix in fixes:
        print(f"\n• {fix['msg'].company.name} - {fix['msg'].subject[:50]}")
        print(f"  {fix['old_label']} → {fix['new_label']}")
        print(f"  Reason: {fix['reason']}")

    print("\n" + "=" * 80)
    response = input("\nApply these fixes? (y/n): ").strip().lower()

    if response == "y":
        for fix in fixes:
            msg = fix["msg"]
            msg.ml_label = fix["new_label"]
            msg.reviewed = True  # Mark as reviewed so it's used in training
            msg.save()
            company_name = msg.company.name if msg.company else "No Company"
            print(f"✓ Fixed: {company_name} - {msg.subject[:40]}...")

        print(f"\n✅ Successfully relabeled {len(fixes)} messages!")
        print("\n💡 Consider retraining the ML model:")
        print("   python train_model.py")
    else:
        print("\n❌ No changes made.")
else:
    print("=" * 80)
    print("✅ No mislabeled messages found!")
    print("=" * 80)
