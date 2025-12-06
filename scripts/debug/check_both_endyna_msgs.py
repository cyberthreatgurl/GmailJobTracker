"""Check both Endyna messages and their threads."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Get both messages
msg1 = Message.objects.get(id=1167)  # Application
msg2 = Message.objects.get(id=1452)  # Interview

print("Message 1 (Application):")
print(f"  ID: {msg1.id}")
print(f"  Thread: {msg1.thread_id}")
print(f"  Timestamp: {msg1.timestamp}")
print(f"  Label: {msg1.ml_label}")
print(f"  Subject: {msg1.subject}")
print()

print("Message 2 (Interview):")
print(f"  ID: {msg2.id}")
print(f"  Thread: {msg2.thread_id}")
print(f"  Timestamp: {msg2.timestamp}")
print(f"  Label: {msg2.ml_label}")
print(f"  Subject: {msg2.subject}")
print()

print(f"Same thread? {msg1.thread_id == msg2.thread_id}")
print()

# Check ThreadTracking for both
apps = ThreadTracking.objects.filter(thread_id__in=[msg1.thread_id, msg2.thread_id])
print(f"ThreadTracking records: {apps.count()}")
for app in apps:
    print(f"\nThreadTracking ID: {app.id}")
    print(f"  Thread: {app.thread_id}")
    print(f"  Company: {app.company.name if app.company else 'None'}")
    print(f"  sent_date: {app.sent_date}")
    print(f"  interview_date: {app.interview_date}")
    print(f"  ml_label: {app.ml_label}")
