"""Check Endyna message processing order."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Get all messages for the thread
thread_id = "19a173c6b0b6b52d"
messages = Message.objects.filter(thread_id=thread_id).order_by("timestamp")

print(f"Thread: {thread_id}")
print(f"Messages in thread: {messages.count()}\n")

for m in messages:
    print(f"Message ID: {m.id}")
    print(f"  Timestamp: {m.timestamp}")
    print(f"  Label: {m.ml_label}")
    print(f"  Subject: {m.subject}")
    print(f"  Reviewed: {m.reviewed}")
    print()

# Check ThreadTracking
app = ThreadTracking.objects.get(thread_id=thread_id)
print(f"ThreadTracking ID: {app.id}")
print(f"  sent_date: {app.sent_date}")
print(f"  interview_date: {app.interview_date}")
print(f"  rejection_date: {app.rejection_date}")
print(f"  ml_label: {app.ml_label}")
print(f"  status: {app.status}")
