#!/usr/bin/env python
"""Fix AstraZeneca duplicate ThreadTracking records.

Merges the prescreen thread into the application thread.
"""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message


def main():
    # Check current state
    print("Current AstraZeneca ThreadTracking records:")
    for tt in ThreadTracking.objects.filter(company_id=212):
        print(f"  {tt.thread_id}: ml_label={tt.ml_label}, prescreen_date={tt.prescreen_date}")

    # Delete the prescreen-only ThreadTracking (if it still exists)
    try:
        prescreen_tt = ThreadTracking.objects.get(thread_id='19bff166c135ba4b')
        print(f"\nDeleting redundant prescreen-only ThreadTracking:")
        print(f"  thread_id: {prescreen_tt.thread_id}")
        prescreen_tt.delete()
        print("✅ Deleted")
    except ThreadTracking.DoesNotExist:
        print("\nPrescreen-only ThreadTracking already deleted.")

    # Verify the application thread still has the prescreen_date
    app_tt = ThreadTracking.objects.get(thread_id='eml_298574105fc961487e7efe4ffa3dfb29')
    print(f"\nRemaining application ThreadTracking:")
    print(f"  thread_id: {app_tt.thread_id}")
    print(f"  prescreen_date: {app_tt.prescreen_date}")

    # Update the prescreen message to point to the application thread
    try:
        prescreen_msg = Message.objects.get(msg_id='19bff166c135ba4b')
        print(f"\nUpdating prescreen message thread_id:")
        print(f"  Before: {prescreen_msg.thread_id}")
        prescreen_msg.thread_id = 'eml_298574105fc961487e7efe4ffa3dfb29'
        prescreen_msg.save()
        print(f"  After: {prescreen_msg.thread_id}")
    except Message.DoesNotExist:
        print("\nPrescreen message not found.")

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
