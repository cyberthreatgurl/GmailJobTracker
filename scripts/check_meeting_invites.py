import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
import re

print("=== Searching for Microsoft Teams meeting invites ===")
teams_msgs = Message.objects.filter(body__icontains="Microsoft Teams").exclude(
    ml_label="noise"
)
print(f"Total found: {teams_msgs.count()}\n")

for msg in teams_msgs[:20]:  # Show first 20
    print(f"Subject: {msg.subject[:80]}")
    print(f'Company: {msg.company.name if msg.company else "None"}')
    print(f"ML Label: {msg.ml_label}")
    print(f"Confidence: {msg.confidence:.2f}")
    print(f"Timestamp: {msg.timestamp}")
    # Check if body has meeting details
    has_meeting_id = "meeting id" in msg.body.lower()
    has_join_link = bool(
        re.search(r"join.*meeting|teams.microsoft.com", msg.body, re.I)
    )
    print(f"Has Meeting ID: {has_meeting_id}, Has Join Link: {has_join_link}")
    print("-" * 80)

print("\n=== Searching for Google Meet/Calendar invites ===")
google_msgs = Message.objects.filter(
    body__iregex=r"(google meet|meet.google.com|calendar invitation)"
).exclude(ml_label="noise")
print(f"Total found: {google_msgs.count()}\n")

for msg in google_msgs[:20]:  # Show first 20
    print(f"Subject: {msg.subject[:80]}")
    print(f'Company: {msg.company.name if msg.company else "None"}')
    print(f"ML Label: {msg.ml_label}")
    print(f"Confidence: {msg.confidence:.2f}")
    print(f"Timestamp: {msg.timestamp}")
    print("-" * 80)

print("\n=== Searching for Zoom meeting invites ===")
zoom_msgs = Message.objects.filter(body__icontains="zoom.us").exclude(ml_label="noise")
print(f"Total found: {zoom_msgs.count()}\n")

for msg in zoom_msgs[:20]:  # Show first 20
    print(f"Subject: {msg.subject[:80]}")
    print(f'Company: {msg.company.name if msg.company else "None"}')
    print(f"ML Label: {msg.ml_label}")
    print(f"Confidence: {msg.confidence:.2f}")
    print(f"Timestamp: {msg.timestamp}")
    print("-" * 80)

print("\n=== Summary by ML Label ===")
print("\nMicrosoft Teams:")
for label in ["interview_invite", "other", "job_application", "response", "follow_up"]:
    count = teams_msgs.filter(ml_label=label).count()
    if count > 0:
        print(f"  {label}: {count}")

print("\nGoogle Meet:")
for label in ["interview_invite", "other", "job_application", "response", "follow_up"]:
    count = google_msgs.filter(ml_label=label).count()
    if count > 0:
        print(f"  {label}: {count}")

print("\nZoom:")
for label in ["interview_invite", "other", "job_application", "response", "follow_up"]:
    count = zoom_msgs.filter(ml_label=label).count()
    if count > 0:
        print(f"  {label}: {count}")
