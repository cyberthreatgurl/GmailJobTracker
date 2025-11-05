#!/usr/bin/env python
"""Debug why Guidehouse Federal is showing in Interviews With box."""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Application, Message

# Find Guidehouse Federal (company_id=38)
company = Company.objects.filter(id=38).first()
if not company:
    print("Company ID 38 not found!")
    sys.exit(1)

print(f"\n{'='*80}")
print(f"COMPANY: {company.name} (ID: {company.id})")
print(f"{'='*80}\n")

# Check Applications
apps = ThreadTracking.objects.filter(company_id=38).order_by('-sent_date')
print(f"APPLICATIONS: {apps.count()}\n")
for app in apps:
    print(f"  Thread: {app.thread_id}")
    print(f"  Job Title: {app.job_title}")
    print(f"  ML Label: {app.ml_label}")
    print(f"  Status: {app.status}")
    print(f"  Sent Date: {app.sent_date}")
    print(f"  Interview Date: {app.interview_date}")
    print(f"  Rejection Date: {app.rejection_date}")
    print(f"  Reviewed: {app.reviewed}")
    print()

# Check Messages
messages = Message.objects.filter(company_id=38).order_by('-timestamp')
print(f"\nMESSAGES: {messages.count()}\n")
for msg in messages:
    print(f"  msg_id: {msg.msg_id}")
    print(f"  Subject: {msg.subject[:70]}")
    print(f"  ML Label: {msg.ml_label}")
    print(f"  Confidence: {msg.confidence:.2%}")
    print(f"  Reviewed: {msg.reviewed}")
    print(f"  Timestamp: {msg.timestamp}")
    print()

# Check specifically for interview-related labels
interview_messages = messages.filter(ml_label__in=['interview_invite', 'interview'])
print(f"\nINTERVIEW MESSAGES: {interview_messages.count()}\n")
for msg in interview_messages:
    print(f"  ⚠️  {msg.ml_label}: {msg.subject[:70]}")
    print(f"     Confidence: {msg.confidence:.2%}, Reviewed: {msg.reviewed}")
    print()

# Check what makes it show in "Interviews With" box
# This typically requires: Application.interview_date IS NOT NULL or Message.ml_label in interview labels
apps_with_interview = apps.filter(interview_date__isnull=False)
print(f"\nAPPLICATIONS WITH interview_date SET: {apps_with_interview.count()}\n")
for app in apps_with_interview:
    print(f"  Interview Date: {app.interview_date}")
    print(f"  Job: {app.job_title}")
    print()

print(f"\n{'='*80}")
print("DIAGNOSIS:")
print(f"{'='*80}")
if interview_messages.exists():
    print("❌ Found messages with interview labels")
    print("   → These are causing the company to appear in Interviews With box")
elif apps_with_interview.exists():
    print("❌ Found applications with interview_date set")
    print("   → These are causing the company to appear in Interviews With box")
else:
    print("✓ No obvious interview indicators found")
    print("  Need to check dashboard query logic")

