#!/usr/bin/env python
"""Check Booz Allen application status in dashboard queries."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.db.models import Exists, OuterRef

from tracker.models import Company, Message, ThreadTracking

print("\n" + "=" * 70)
print("BOOZ ALLEN APPLICATION DASHBOARD DEBUG")
print("=" * 70)

# Check the Booz Allen message
bah_msg = Message.objects.filter(
    sender__icontains="bah.com", subject__icontains="Thank you for applying"
).first()

if bah_msg:
    print(f"\n✅ Booz Allen Message Found:")
    print(f"  ID: {bah_msg.id}")
    print(f"  Subject: {bah_msg.subject}")
    print(f"  Label: {bah_msg.ml_label}")
    print(f"  Company: {bah_msg.company}")
    print(f"  Thread ID: {bah_msg.thread_id}")
    print(f"  Timestamp: {bah_msg.timestamp}")

    # Check if there's a ThreadTracking for this
    tt = ThreadTracking.objects.filter(thread_id=bah_msg.thread_id).first()
    if tt:
        print(f"\n✅ ThreadTracking Found:")
        print(f"  ID: {tt.id}")
        print(f"  Company: {tt.company}")
        print(f"  sent_date: {tt.sent_date}")
        print(f"  Label: {tt.ml_label}")
        print(f"  Status: {tt.status}")
    else:
        print(f"\n❌ No ThreadTracking found for thread {bah_msg.thread_id}")
        print(f"   This is the problem! Need to create ThreadTracking.")

    # Check the dashboard query
    job_app_exists = Exists(
        Message.objects.filter(
            thread_id=OuterRef("thread_id"),
            ml_label__in=["job_application", "application"],
        )
    )
    app_qs = (
        ThreadTracking.objects.filter(sent_date__isnull=False, company__isnull=False)
        .annotate(has_job_app=job_app_exists)
        .filter(has_job_app=True)
    )

    # Check if Booz Allen ThreadTracking would be included
    if tt:
        matches = app_qs.filter(id=tt.id).exists()
        print(f"\n📊 Dashboard Query Inclusion:")
        print(f"  Would be included: {matches}")
        if not matches:
            print(f"\n❌ Reasons why NOT included:")
            print(f"  • sent_date is None: {tt.sent_date is None}")
            print(f"  • company is None: {tt.company is None}")
            # Check if has_job_app
            has_app = Message.objects.filter(
                thread_id=tt.thread_id, ml_label__in=["job_application", "application"]
            ).exists()
            print(f"  • No job_application/application in thread: {not has_app}")

            # Show what labels exist in the thread
            thread_msgs = Message.objects.filter(thread_id=tt.thread_id).values_list(
                "ml_label", flat=True
            )
            print(f"\n  Thread messages labels: {list(thread_msgs)}")
    else:
        print(f"\n❌ Cannot check dashboard query - no ThreadTracking exists!")

    # Check all Booz Allen companies
    print(f"\n📋 All Booz Allen related companies:")
    bah_companies = Company.objects.filter(name__icontains="booz")
    for comp in bah_companies:
        print(f"  • {comp.name} (ID: {comp.id})")

else:
    print("\n❌ Booz Allen message not found")

print("=" * 70 + "\n")
