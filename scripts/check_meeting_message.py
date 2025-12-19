import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, Company

c = Company.objects.filter(name__icontains="Endyna").first()

print('=== "Meeting with Kelly Shaw" message ===')
msg = Message.objects.filter(
    company=c, subject__icontains="Meeting with Kelly Shaw"
).first()

if msg:
    print(f"Subject: {msg.subject}")
    print(f"ML Label: {msg.ml_label}")
    print(f"Confidence: {msg.confidence}")
    print(f"Timestamp: {msg.timestamp}")
    print(f"Sender: {msg.sender}")
    print(f"\nBody (first 500 chars):")
    print(msg.body[:500])
else:
    print("Message not found")
