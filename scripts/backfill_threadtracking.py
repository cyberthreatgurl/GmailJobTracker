#!/usr/bin/env python3
"""Backfill missing ThreadTracking records for job_application messages."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message, ThreadTracking, Company
from datetime import timedelta

print("=" * 80)
print("BACKFILL MISSING THREADTRACKING RECORDS")
print("=" * 80)

# Find all job_application messages WITHOUT ThreadTracking
job_app_messages = Message.objects.filter(
    ml_label__in=["job_application", "application"],
    company__isnull=False,
).exclude(company__status="headhunter")

print(f"\nTotal job_application messages: {job_app_messages.count()}")

missing_tt = []
for msg in job_app_messages:
    tt_exists = ThreadTracking.objects.filter(thread_id=msg.thread_id).exists()
    if not tt_exists:
        missing_tt.append(msg)

print(f"Messages missing ThreadTracking: {len(missing_tt)}\n")

if not missing_tt:
    print("✅ All job_application messages have ThreadTracking records!")
    print("=" * 80)
    sys.exit(0)

print("Missing ThreadTracking for:")
for msg in missing_tt:
    print(f"  - {msg.company.name:30} {msg.timestamp.date()} {msg.subject[:50]}")

# Create ThreadTracking records
print(f"\nCreating {len(missing_tt)} ThreadTracking records...")

created_count = 0
for msg in missing_tt:
    try:
        # Extract job info from subject (basic heuristic)
        job_title = ""
        job_id = ""
        subject = msg.subject or ""

        # Try to extract job title from subject
        if ":" in subject:
            parts = subject.split(":", 1)
            if len(parts) == 2:
                job_title = parts[1].strip()[:255]

        if not job_title:
            job_title = subject[:255] if subject else "Unknown"

        tt, created = ThreadTracking.objects.get_or_create(
            thread_id=msg.thread_id,
            defaults={
                "company": msg.company,
                "company_source": msg.company_source or "backfill",
                "job_title": job_title,
                "job_id": job_id,
                "status": "application",
                "sent_date": msg.timestamp.date(),
                "rejection_date": None,
                "interview_date": None,
                "ml_label": msg.ml_label,
                "ml_confidence": msg.confidence or 0.95,
                "reviewed": msg.reviewed,
            },
        )

        if created:
            created_count += 1
            print(
                f"  ✓ Created ThreadTracking for {msg.company.name} - {msg.subject[:40]}"
            )
        else:
            print(f"  ⚠️  ThreadTracking already exists for {msg.company.name}")

    except Exception as e:
        print(f"  ❌ Failed to create ThreadTracking for {msg.subject[:40]}: {e}")

print(f"\n✅ Backfill complete: {created_count} ThreadTracking records created")
print("=" * 80)
