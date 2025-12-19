#!/usr/bin/env python
"""
Backfill missing interview_date and rejection_date fields for Applications
that have ML labels but no corresponding date set.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking


def backfill_dates():
    # Fix interviews
    interviews_fixed = 0
    for app in ThreadTracking.objects.filter(
        ml_label="interview_invite", interview_date__isnull=True
    ):
        msg = Message.objects.filter(
            thread_id=app.thread_id, ml_label="interview_invite"
        ).first()
        if msg:
            app.interview_date = msg.timestamp.date()
            app.save()
            interviews_fixed += 1
            company_name = app.company.name if app.company else "Unknown"
            print(f"Fixed interview: {company_name} - {msg.timestamp.date()}")

    # Fix rejections
    rejections_fixed = 0
    for app in ThreadTracking.objects.filter(
        ml_label="rejected", rejection_date__isnull=True
    ):
        msg = Message.objects.filter(
            thread_id=app.thread_id, ml_label="rejected"
        ).first()
        if msg:
            app.rejection_date = msg.timestamp.date()
            app.save()
            rejections_fixed += 1
            company_name = app.company.name if app.company else "Unknown"
            print(f"Fixed rejection: {company_name} - {msg.timestamp.date()}")

    print(
        f"\nSummary: Fixed {interviews_fixed} interview dates and {rejections_fixed} rejection dates"
    )

    # Verify dashboard counts
    from datetime import datetime, timedelta

    seven_days_ago = datetime.now().date() - timedelta(days=7)

    recent_interviews = ThreadTracking.objects.filter(
        interview_date__gte=seven_days_ago
    ).count()
    recent_rejections = ThreadTracking.objects.filter(
        rejection_date__gte=seven_days_ago
    ).count()

    print(f"\nDashboard verification:")
    print(f"  Interviews in last 7 days: {recent_interviews}")
    print(f"  Rejections in last 7 days: {recent_rejections}")


if __name__ == "__main__":
    backfill_dates()
