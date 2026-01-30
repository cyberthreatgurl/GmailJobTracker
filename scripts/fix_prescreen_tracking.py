#!/usr/bin/env python
"""Create ThreadTracking for existing prescreen messages that don't have one."""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message
from django.utils import timezone

# Find all prescreen messages without corresponding ThreadTracking
prescreen_msgs = Message.objects.filter(ml_label="prescreen")
print(f"Found {prescreen_msgs.count()} prescreen messages")

created_count = 0
for msg in prescreen_msgs:
    existing = ThreadTracking.objects.filter(thread_id=msg.thread_id).exists()
    if not existing and msg.company:
        tt = ThreadTracking.objects.create(
            thread_id=msg.thread_id,
            company=msg.company,
            company_source=msg.company_source or "prescreen_backfill",
            job_title="",
            job_id="",
            status="prescreen",
            sent_date=timezone.localtime(msg.timestamp).date(),
            prescreen_date=timezone.localtime(msg.timestamp).date(),
            ml_label="prescreen",
            ml_confidence=msg.confidence or 0.0,
            reviewed=msg.reviewed,
        )
        created_count += 1
        print(f"Created ThreadTracking for {msg.company.name}: prescreen_date={tt.prescreen_date}")
    elif existing:
        # Update existing ThreadTracking with prescreen_date if missing
        tt = ThreadTracking.objects.get(thread_id=msg.thread_id)
        if not tt.prescreen_date:
            tt.prescreen_date = timezone.localtime(msg.timestamp).date()
            tt.save()
            print(f"Updated ThreadTracking for {msg.company.name if msg.company else 'unknown'}: prescreen_date={tt.prescreen_date}")
    else:
        print(f"Skipped message {msg.msg_id}: no company")

print(f"\nCreated {created_count} new ThreadTracking records")
