#!/usr/bin/env python3
"""Check what ml_label the missing ThreadTracking messages have."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message, ThreadTracking

print("=" * 80)
print("MESSAGES WITH MISSING THREADTRACKING")
print("=" * 80)

# The 4 messages that don't have ThreadTracking
missing_threads = [
    "19a56992c987cb4f",  # Millennium - Indeed Application: Cyber Security Engineer
    "19a56999a20e487f",  # Millennium - Thank You for Applying
    "19a569cd27ab8d46",  # Tatitlek - Indeed Application: Senior Systems
    "19a647bc05544c25",  # Booz Allen - Thank you for applying (Nov 8)
]

for thread_id in missing_threads:
    msg = Message.objects.filter(thread_id=thread_id).first()
    if msg:
        print(f"\nThread: {thread_id}")
        print(f"  Company: {msg.company.name if msg.company else 'None'}")
        print(f"  Subject: {msg.subject[:60]}")
        print(f"  ml_label: {msg.ml_label}")
        print(f"  confidence: {msg.confidence}")
        print(f"  timestamp: {msg.timestamp}")
        print(f"  sender: {msg.sender[:50]}")

        # Check if ThreadTracking exists
        tt = ThreadTracking.objects.filter(thread_id=thread_id).first()
        if tt:
            print(f"  ThreadTracking: ✅ EXISTS (ml_label={tt.ml_label})")
        else:
            print(f"  ThreadTracking: ❌ MISSING")
    else:
        print(f"\n❌ No message found for thread {thread_id}")

print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)
print("\nIf ml_label == 'job_application', ThreadTracking SHOULD have been created.")
print("If ml_label != 'job_application', that's why ThreadTracking is missing.")
print("=" * 80)
