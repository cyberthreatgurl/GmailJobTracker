import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

print("=== All Zoom messages labeled as interview_invite ===")
zoom_interview_msgs = (
    Message.objects.filter(body__icontains="zoom.us", ml_label="interview_invite")
    .exclude(ml_label="noise")
    .order_by("-timestamp")
)

print(f"Total count: {zoom_interview_msgs.count()}\n")

for msg in zoom_interview_msgs:
    print(f'Date: {msg.timestamp.strftime("%Y-%m-%d")}')
    print(f"Subject: {msg.subject}")
    print(f'Company: {msg.company.name if msg.company else "None"}')
    print(f"Confidence: {msg.confidence:.2f}")
    print(f"Sender: {msg.sender[:80]}")
    # Show snippet of body
    body_snippet = msg.body[:200].replace("\n", " ")
    print(f"Body snippet: {body_snippet}...")
    print("-" * 80)
