#!/usr/bin/env python3
"""Check job_application Messages vs ThreadTracking."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

from tracker.models import Message, ThreadTracking
from django.utils.timezone import now
from datetime import timedelta

week_cutoff = (now() - timedelta(days=7)).date()

print("=" * 80)
print("JOB APPLICATION MESSAGES (last 7 days)")
print("=" * 80)

job_app_messages = Message.objects.filter(
    ml_label__in=['job_application', 'application'],
    timestamp__gte=now() - timedelta(days=7),
    company__isnull=False,
).order_by('timestamp')

print(f"\nTotal job_application Messages: {job_app_messages.count()}\n")

for msg in job_app_messages:
    print(f"Company: {msg.company.name:30} Date: {msg.timestamp.date()}")
    print(f"  Subject: {msg.subject[:60]}")
    print(f"  Thread: {msg.thread_id}")
    
    # Check if ThreadTracking exists for this thread
    thread = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
    if thread:
        print(f"  ThreadTracking: sent_date={thread.sent_date}, ml_label={thread.ml_label}, status={thread.status}")
    else:
        print(f"  ThreadTracking: ❌ MISSING")
    print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print("Messages labeled job_application:", job_app_messages.count())
print("Distinct companies from those messages:", job_app_messages.values('company_id').distinct().count())

# Now check ThreadTracking perspective
threads_in_range = ThreadTracking.objects.filter(
    sent_date__gte=week_cutoff,
    company__isnull=False
).exclude(ml_label='noise').exclude(company__status='headhunter')

print(f"\nThreadTracking rows (sent_date >= {week_cutoff}, non-noise, non-headhunter): {threads_in_range.count()}")
print("=" * 80)
