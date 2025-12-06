"""Create ThreadTracking for Endyna interview thread."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Get the interview message
msg = Message.objects.get(id=1452)
print(f"Interview message:")
print(f"  Thread: {msg.thread_id}")
print(f"  Company: {msg.company.name if msg.company else 'None'}")
print(f"  Date: {msg.timestamp.date()}")
print(f"  Subject: {msg.subject}")
print()

# Check if ThreadTracking exists
existing = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
if existing:
    print(f"ThreadTracking already exists: {existing.id}")
else:
    print("No ThreadTracking record found. Creating one...")

    # Create ThreadTracking
    app = ThreadTracking.objects.create(
        thread_id=msg.thread_id,
        company=msg.company,
        job_title="Cyber PM",  # From subject
        sent_date=msg.timestamp.date(),  # Use interview date as sent_date
        interview_date=msg.timestamp.date(),
        ml_label="interview_invite",
        ml_confidence=msg.confidence or 0.0,
        reviewed=True,
        company_source=msg.company_source or "manual",
    )
    print(f"✅ Created ThreadTracking id={app.id}")
    print(f"   interview_date: {app.interview_date}")
    print(f"   company: {app.company.name}")
