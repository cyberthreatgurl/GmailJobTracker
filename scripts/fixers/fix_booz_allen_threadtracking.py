#!/usr/bin/env python
"""Create missing ThreadTracking for Booz Allen application."""

import os

import django
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()


from tracker.models import Message, ThreadTracking

print("\n" + "=" * 70)
print("CREATE THREADTRACKING FOR BOOZ ALLEN APPLICATION")
print("=" * 70)

# Get the Booz Allen message
bah_msg = Message.objects.filter(
    sender__icontains="bah.com", subject__icontains="Thank you for applying"
).first()

if not bah_msg:
    print("❌ Booz Allen message not found!")
    exit(1)

print(f"\n📧 Message Details:")
print(f"  ID: {bah_msg.id}")
print(f"  Subject: {bah_msg.subject}")
print(f"  Label: {bah_msg.ml_label}")
print(f"  Company: {bah_msg.company}")
print(f"  Thread ID: {bah_msg.thread_id}")
print(f"  Timestamp: {bah_msg.timestamp}")

# Check if ThreadTracking already exists
existing_tt = ThreadTracking.objects.filter(thread_id=bah_msg.thread_id).first()
if existing_tt:
    print(f"\n⚠️ ThreadTracking already exists!")
    print(f"  ID: {existing_tt.id}")
    print(f"  Company: {existing_tt.company}")
    print(f"  sent_date: {existing_tt.sent_date}")
    print(f"  Label: {existing_tt.ml_label}")
    exit(0)

# Create ThreadTracking
print(f"\n✅ Creating ThreadTracking...")

# Extract job title from subject if possible
subject = bah_msg.subject
# Subject is "Thank you for applying" but the actual job would be in body
# Let's parse from body text: "your application for the OT Cybersecurity Analyst position"
job_title = "OT Cybersecurity Analyst"  # From the email body
job_id = "R0227717"  # From the email body

tt = ThreadTracking.objects.create(
    thread_id=bah_msg.thread_id,
    company=bah_msg.company,
    ml_label=bah_msg.ml_label,
    sent_date=timezone.localtime(bah_msg.timestamp).date(),  # Use message timestamp as sent_date
    reviewed=bah_msg.reviewed,
    ml_confidence=bah_msg.confidence or 0.0,
    job_title=job_title,
    job_id=job_id,
    status="pending",
    company_source=bah_msg.company_source or "domain_mapping",
)

print(f"\n✅ ThreadTracking Created:")
print(f"  ID: {tt.id}")
print(f"  Thread ID: {tt.thread_id}")
print(f"  Company: {tt.company}")
print(f"  Job Title: {tt.job_title}")
print(f"  Job ID: {tt.job_id}")
print(f"  sent_date: {tt.sent_date}")
print(f"  Label: {tt.ml_label}")
print(f"  Confidence: {tt.ml_confidence}")
print(f"  Status: {tt.status}")

# Verify it would now appear in dashboard query
from django.db.models import Exists, OuterRef

job_app_exists = Exists(
    Message.objects.filter(
        thread_id=OuterRef("thread_id"),
        ml_label__in=["job_application", "application"],
    )
)
app_qs = (
    ThreadTracking.objects.filter(sent_date__isnull=False, company__isnull=False)
    .annotate(has_job_app=job_app_exists)
    .filter(has_job_app=True)
)

matches = app_qs.filter(id=tt.id).exists()
print(f"\n📊 Dashboard Verification:")
print(f"  Would appear in 'Applications Sent': {matches}")

if matches:
    print(f"\n✅ SUCCESS! Booz Allen should now appear in dashboard!")
else:
    print(f"\n❌ FAILED! Something is still wrong.")

print("=" * 70 + "\n")
