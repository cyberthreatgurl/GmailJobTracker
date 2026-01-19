"""Create ThreadTracking records for Millennium interview messages that are missing them."""

import os
import sys
import django
from datetime import timedelta
from django.utils import timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Find Millennium interview messages without ThreadTracking
millennium_interviews = Message.objects.filter(
    company__name="Millennium Corporation", ml_label="interview_invite"
)

print(f"Found {millennium_interviews.count()} Millennium interview message(s)\n")

created_count = 0

for msg in millennium_interviews:
    # Check if ThreadTracking already exists
    exists = ThreadTracking.objects.filter(thread_id=msg.thread_id).exists()

    if exists:
        print(f"✓ ThreadTracking already exists for thread {msg.thread_id}")
        continue

    # Create ThreadTracking record
    local_timestamp = timezone.localtime(msg.timestamp)
    interview_date = (local_timestamp + timedelta(days=7)).date()

    thread = ThreadTracking.objects.create(
        thread_id=msg.thread_id,
        company=msg.company,
        company_source=msg.company_source or "ml_extraction",
        job_title=msg.subject.replace("Response Requested -", "")
        .replace("- Millennium Corporation", "")
        .strip(),
        job_id="",
        status="interview",
        sent_date=local_timestamp.date(),
        interview_date=interview_date,
        interview_completed=False,
        ml_label=msg.ml_label,
        ml_confidence=msg.confidence,
        reviewed=False,
    )

    print(f"✅ Created ThreadTracking for: {msg.subject}")
    print(f"   Thread ID: {msg.thread_id}")
    print(f"   Interview Date: {interview_date}")
    print(f"   Job Title: {thread.job_title}")
    print()

    created_count += 1

print(f"\n{'=' * 70}")
print(f"Created {created_count} new ThreadTracking record(s)")
print(f"{'=' * 70}")

# Show upcoming interviews
upcoming = (
    ThreadTracking.objects.filter(
        interview_date__gte="2025-11-08",
        interview_completed=False,
        company__isnull=False,
    )
    .select_related("company")
    .order_by("interview_date")
)

print(f"\n📅 Upcoming Interviews ({upcoming.count()}):")
for t in upcoming:
    print(f"  • {t.company.name}: {t.job_title[:50]}")
    print(f"    Date: {t.interview_date} | Completed: {t.interview_completed}")
