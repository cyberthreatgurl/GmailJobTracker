#!/usr/bin/env python
"""Find and fix ThreadTracking records missing prescreen_date or interview_date."""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking
from django.utils import timezone

def find_missing_dates():
    """Find messages with labels but missing dates in ThreadTracking."""
    
    print("=" * 70)
    print("PRESCREEN messages without prescreen_date in ThreadTracking")
    print("=" * 70)
    
    prescreen_missing = []
    prescreen_msgs = Message.objects.filter(ml_label="prescreen").select_related("company")
    for msg in prescreen_msgs:
        # Skip replies (they shouldn't set prescreen_date)
        if msg.subject and msg.subject.strip().lower().startswith(("re:", "fwd:", "fw:")):
            continue
        tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if tt and not tt.prescreen_date:
            prescreen_missing.append((msg, tt))
            print(f"  {msg.company.name if msg.company else 'Unknown'}")
            print(f"    Subject: {msg.subject[:60]}")
            print(f"    Thread: {msg.thread_id}, Date: {msg.timestamp.date()}")
            print()
        elif not tt:
            print(f"  NO ThreadTracking: {msg.company.name if msg.company else 'Unknown'}")
            print(f"    Subject: {msg.subject[:60]}")
            print(f"    Thread: {msg.thread_id}, Date: {msg.timestamp.date()}")
            print()
    
    print()
    print("=" * 70)
    print("INTERVIEW_INVITE messages without interview_date in ThreadTracking")
    print("=" * 70)
    
    interview_missing = []
    interview_msgs = Message.objects.filter(ml_label="interview_invite").select_related("company")
    for msg in interview_msgs:
        tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if tt and not tt.interview_date:
            interview_missing.append((msg, tt))
            print(f"  {msg.company.name if msg.company else 'Unknown'}")
            print(f"    Subject: {msg.subject[:60]}")
            print(f"    Thread: {msg.thread_id}, Date: {msg.timestamp.date()}")
            print()
        elif not tt:
            print(f"  NO ThreadTracking: {msg.company.name if msg.company else 'Unknown'}")
            print(f"    Subject: {msg.subject[:60]}")
            print(f"    Thread: {msg.thread_id}, Date: {msg.timestamp.date()}")
            print()
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Prescreen messages needing date update: {len(prescreen_missing)}")
    print(f"Interview messages needing date update: {len(interview_missing)}")
    
    return prescreen_missing, interview_missing


def fix_missing_dates(prescreen_missing, interview_missing):
    """Update ThreadTracking records with missing dates."""
    
    print()
    print("=" * 70)
    print("FIXING MISSING DATES")
    print("=" * 70)
    
    for msg, tt in prescreen_missing:
        tt.prescreen_date = timezone.localtime(msg.timestamp).date()
        tt.save()
        print(f"  Set prescreen_date={tt.prescreen_date} for {msg.company.name if msg.company else 'Unknown'}")
    
    for msg, tt in interview_missing:
        tt.interview_date = timezone.localtime(msg.timestamp).date()
        tt.save()
        print(f"  Set interview_date={tt.interview_date} for {msg.company.name if msg.company else 'Unknown'}")
    
    print()
    print(f"Updated {len(prescreen_missing)} prescreen dates")
    print(f"Updated {len(interview_missing)} interview dates")


if __name__ == "__main__":
    prescreen_missing, interview_missing = find_missing_dates()
    
    if prescreen_missing or interview_missing:
        response = input("\nDo you want to fix these missing dates? (y/n): ")
        if response.lower() == "y":
            fix_missing_dates(prescreen_missing, interview_missing)
        else:
            print("No changes made.")
    else:
        print("\nNo missing dates found!")
