#!/usr/bin/env python
"""Merge duplicate American Systems threads."""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# The canonical thread (first one - original subject)
canonical_thread = "19bd313eb8e87b5b"
duplicate_thread = "19bd6bdc0bb31651"

# Move all messages from duplicate to canonical
msg_count = Message.objects.filter(thread_id=duplicate_thread).update(thread_id=canonical_thread)
print(f"Moved {msg_count} messages from {duplicate_thread} to {canonical_thread}")

# Get the ThreadTracking records
canonical_tt = ThreadTracking.objects.filter(thread_id=canonical_thread).first()
duplicate_tt = ThreadTracking.objects.filter(thread_id=duplicate_thread).first()

if canonical_tt and duplicate_tt:
    # Keep the earlier prescreen_date
    if duplicate_tt.prescreen_date and (not canonical_tt.prescreen_date or duplicate_tt.prescreen_date < canonical_tt.prescreen_date):
        canonical_tt.prescreen_date = duplicate_tt.prescreen_date
        canonical_tt.save()
        print(f"Updated canonical prescreen_date to {canonical_tt.prescreen_date}")
    
    # Delete the duplicate ThreadTracking
    duplicate_tt.delete()
    print(f"Deleted duplicate ThreadTracking for thread {duplicate_thread}")
elif duplicate_tt:
    # Just rename the duplicate to canonical
    duplicate_tt.thread_id = canonical_thread
    duplicate_tt.save()
    print(f"Renamed ThreadTracking thread_id to {canonical_thread}")

# Verify the merge
print("\n=== Merged thread now has: ===")
msgs = Message.objects.filter(thread_id=canonical_thread).order_by("timestamp")
for m in msgs:
    print(f"  {m.timestamp.date()} - {m.ml_label}: {m.subject[:50]}")

tt = ThreadTracking.objects.filter(thread_id=canonical_thread).first()
if tt:
    print(f"\nThreadTracking: prescreen_date={tt.prescreen_date}")

print("\nDone!")
