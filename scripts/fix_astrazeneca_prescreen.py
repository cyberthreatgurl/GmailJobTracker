#!/usr/bin/env python
"""Fix AstraZeneca (company=212) ThreadTracking record.

The message was manually changed from interview_invite to prescreen,
but the ThreadTracking.prescreen_date was not updated.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message, ThreadTracking


def main():
    """Fix AstraZeneca ThreadTracking record."""
    # Find AstraZeneca
    try:
        company = Company.objects.get(id=212)
        print(f"Found company: {company.name} (id={company.id})")
    except Company.DoesNotExist:
        print("ERROR: Company with id=212 not found")
        return

    # Find prescreen messages for this company
    prescreen_msgs = Message.objects.filter(
        company=company,
        ml_label="prescreen"
    ).order_by("timestamp")

    print(f"\nPrescreen messages for {company.name}:")
    for msg in prescreen_msgs:
        print(f"  - {msg.msg_id}: {msg.subject[:60]}...")
        print(f"    Date: {msg.timestamp}, Thread: {msg.thread_id}")

    if not prescreen_msgs.exists():
        print("No prescreen messages found!")
        return

    # Get the earliest prescreen message
    earliest_prescreen = prescreen_msgs.first()
    prescreen_date = earliest_prescreen.timestamp.date() if earliest_prescreen.timestamp else None
    thread_id = earliest_prescreen.thread_id

    print(f"\nEarliest prescreen date: {prescreen_date}")
    print(f"Thread ID: {thread_id}")

    # Find ThreadTracking for this thread
    tt = ThreadTracking.objects.filter(thread_id=thread_id).first()
    if tt:
        print(f"\nThreadTracking found:")
        print(f"  - prescreen_date: {tt.prescreen_date}")
        print(f"  - interview_date: {tt.interview_date}")
        print(f"  - ml_label: {tt.ml_label}")

        # Check if we need to fix
        needs_fix = False
        if tt.prescreen_date != prescreen_date:
            print(f"\n⚠️  prescreen_date needs update: {tt.prescreen_date} → {prescreen_date}")
            needs_fix = True
        if tt.ml_label != "prescreen":
            print(f"⚠️  ml_label needs update: {tt.ml_label} → prescreen")
            needs_fix = True
        if tt.interview_date == prescreen_date:
            print(f"⚠️  interview_date should be cleared (was set from incorrect label)")
            needs_fix = True

        if needs_fix:
            confirm = input("\nApply fix? (y/n): ")
            if confirm.lower() == "y":
                tt.prescreen_date = prescreen_date
                tt.ml_label = "prescreen"
                # Only clear interview_date if it matches prescreen_date (was incorrectly set)
                if tt.interview_date == prescreen_date:
                    tt.interview_date = None
                tt.save()
                print("✅ Fixed!")
            else:
                print("Skipped.")
        else:
            print("\n✅ No fix needed.")
    else:
        print(f"\nNo ThreadTracking found for thread {thread_id}")
        # Check if there's a ThreadTracking for this company
        tt_by_company = ThreadTracking.objects.filter(company=company).first()
        if tt_by_company:
            print(f"\nFound ThreadTracking by company (thread_id={tt_by_company.thread_id}):")
            print(f"  - prescreen_date: {tt_by_company.prescreen_date}")
            print(f"  - interview_date: {tt_by_company.interview_date}")
            print(f"  - ml_label: {tt_by_company.ml_label}")


if __name__ == "__main__":
    main()
