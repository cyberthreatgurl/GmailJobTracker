"""Check Viasat messages from nurture.icims.com"""

import os
import django

os.chdir(r"C:\Users\kaver\code\GmailJobTracker")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

# Find all messages from viasat@nurture.icims.com
viasat_messages = Message.objects.filter(
    sender__icontains="viasat@nurture.icims.com"
).order_by("-timestamp")

print(f"Found {viasat_messages.count()} Viasat messages from nurture.icims.com\n")

for msg in viasat_messages:
    print(f"Date: {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Subject: {msg.subject[:70]}")
    print(f"Sender: {msg.sender}")
    print(f"Company: {msg.company.name if msg.company else 'None'}")
    print(f"Company Source: {msg.company_source}")
    print(f"Label: {msg.ml_label}")
    print("-" * 80)
