#!/usr/bin/env python
"""Deep dive into Guidehouse Federal applications to find their origin."""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message

print("\n" + "=" * 80)
print("GUIDEHOUSE FEDERAL - APPLICATION ORIGIN ANALYSIS")
print("=" * 80 + "\n")

apps = ThreadTracking.objects.filter(company_id=38).order_by("-sent_date")

for i, app in enumerate(apps, 1):
    print(f"\n{'─'*80}")
    print(f"APPLICATION {i}: {app.thread_id}")
    print(f"{'─'*80}")
    print(f"Job Title: {app.job_title or '(empty)'}")
    print(f"Job ID: {app.job_id or '(empty)'}")
    print(f"Sent Date: {app.sent_date}")
    print(f"Interview Date: {app.interview_date}")
    print(f"ML Label: {app.ml_label}")
    print(f"Status: {app.status}")
    print(f"Company Source: {app.company_source}")
    print(f"ML Confidence: {app.ml_confidence}")
    print(f"Reviewed: {app.reviewed}")

    # Get all messages in this thread
    messages = Message.objects.filter(thread_id=app.thread_id).order_by("timestamp")
    print(f"\nMessages in thread: {messages.count()}")

    for j, msg in enumerate(messages, 1):
        print(f"\n  Message {j}:")
        print(f"    ID: {msg.msg_id}")
        print(f"    Subject: {msg.subject}")
        print(f"    Sender: {msg.sender}")
        print(f"    ML Label: {msg.ml_label} ({msg.confidence:.1%})")
        print(f"    Company: {msg.company.name if msg.company else 'None'}")
        print(f"    Company Source: {msg.company_source}")
        print(f"    Timestamp: {msg.timestamp}")
        print(f"    Reviewed: {msg.reviewed}")

        # Show first 200 chars of body
        if msg.body:
            body_preview = msg.body.replace("\n", " ").replace("\r", "")[:200]
            print(f"    Body preview: {body_preview}...")

print("\n" + "=" * 80)
print("ANALYSIS QUESTIONS:")
print("=" * 80)
print("1. Which application is the legitimate one you sent?")
print("2. Are the others from:")
print("   - Duplicate message threads?")
print("   - Forwarded/reply chains incorrectly parsed as separate applications?")
print("   - Headhunter/recruiter emails about Guidehouse positions?")
print("   - LinkedIn/job board notifications about Guidehouse?")
print("\n3. Check the senders and subjects to identify the source")

