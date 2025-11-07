#!/usr/bin/env python
"""
Debug script to check dashboard statistics and identify discrepancies.
Run with: python debug_dashboard_stats.py
"""
import os
import sys
import django
from datetime import timedelta

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.db.models import Q, Count
from django.utils.timezone import now
from tracker.models import Message, ThreadTracking, Company

# Get headhunter configuration
try:
    import json
    from pathlib import Path
    companies_path = Path("json/companies.json")
    headhunter_domains = []
    if companies_path.exists():
        with open(companies_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            headhunter_domains = [
                d.strip().lower()
                for d in data.get("headhunter_domains", [])
                if d and isinstance(d, str)
            ]
except Exception as e:
    print(f"Warning: Could not load headhunter domains: {e}")
    headhunter_domains = []

# Get user email
user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()

# Build headhunter exclusion queries
msg_hh_sender_q = Q()
for d in headhunter_domains:
    msg_hh_sender_q |= Q(sender__icontains=f"@{d}")

print("=" * 80)
print("DASHBOARD STATISTICS DEBUG REPORT")
print("=" * 80)
print(f"\nUser Email: {user_email or '(not set)'}")
print(f"Headhunter Domains: {', '.join(headhunter_domains) if headhunter_domains else '(none)'}")
print(f"Date Range: Last 7 days (since {(now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M')})")

# Applications this week
print("\n" + "=" * 80)
print("APPLICATIONS THIS WEEK")
print("=" * 80)
applications_qs = Message.objects.filter(
    ml_label="job_application",
    company__isnull=False
)
if user_email:
    applications_qs = applications_qs.exclude(sender__icontains=user_email)
if headhunter_domains:
    applications_qs = applications_qs.exclude(msg_hh_sender_q)
applications_qs = applications_qs.exclude(ml_label="head_hunter")

apps_this_week = applications_qs.filter(
    timestamp__gte=now() - timedelta(days=7)
)

print(f"\nTotal job_application messages (all time): {applications_qs.count()}")
print(f"Job applications in last 7 days: {apps_this_week.count()}")

if apps_this_week.exists():
    print("\nRecent applications:")
    for msg in apps_this_week.order_by('-timestamp')[:10]:
        print(f"  • {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.company.name if msg.company else 'No Company'} | {msg.subject[:60]}")

# Rejections this week
print("\n" + "=" * 80)
print("REJECTIONS THIS WEEK")
print("=" * 80)
rejections_qs = Message.objects.filter(
    ml_label__in=["rejected", "rejection"],
    timestamp__gte=now() - timedelta(days=7),
    company__isnull=False,
)
if user_email:
    rejections_qs = rejections_qs.exclude(sender__icontains=user_email)
if headhunter_domains:
    rejections_qs = rejections_qs.exclude(msg_hh_sender_q)
rejections_qs = rejections_qs.exclude(ml_label="head_hunter")

print(f"\nRejection messages in last 7 days: {rejections_qs.count()}")

if rejections_qs.exists():
    print("\nRecent rejections:")
    for msg in rejections_qs.order_by('-timestamp'):
        print(f"  • {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.company.name if msg.company else 'No Company'} | Label: {msg.ml_label} | {msg.subject[:60]}")

# Interviews this week
print("\n" + "=" * 80)
print("INTERVIEWS THIS WEEK")
print("=" * 80)
interviews_qs = Message.objects.filter(
    ml_label="interview_invite",
    timestamp__gte=now() - timedelta(days=7),
    company__isnull=False,
)
if user_email:
    interviews_qs = interviews_qs.exclude(sender__icontains=user_email)
if headhunter_domains:
    interviews_qs = interviews_qs.exclude(msg_hh_sender_q)

print(f"\nInterview messages in last 7 days: {interviews_qs.count()}")

if interviews_qs.exists():
    print("\nRecent interview invites:")
    for msg in interviews_qs.order_by('-timestamp'):
        print(f"  • {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.company.name if msg.company else 'No Company'} | {msg.subject[:60]}")

# Check ThreadTracking for interviews
print("\n" + "=" * 80)
print("INTERVIEW DATA FROM THREADTRACKING TABLE")
print("=" * 80)
thread_interviews_week = ThreadTracking.objects.filter(
    interview_date__gte=(now() - timedelta(days=7)).date(),
    company__isnull=False
)
print(f"\nThreads with interview_date in last 7 days: {thread_interviews_week.count()}")

if thread_interviews_week.exists():
    print("\nThreads with recent interview dates:")
    for app in thread_interviews_week.order_by('-interview_date'):
        print(f"  • {app.interview_date} | {app.company.name} | {app.job_title} | Thread: {app.thread_id}")

# Alternative: Messages that might be interviews but not labeled as such
print("\n" + "=" * 80)
print("POTENTIAL UNLABELED INTERVIEWS (Last 7 Days)")
print("=" * 80)
potential_interviews = Message.objects.filter(
    timestamp__gte=now() - timedelta(days=7),
    company__isnull=False
).exclude(
    ml_label__in=["interview_invite", "noise", "head_hunter"]
).filter(
    Q(subject__icontains="interview") |
    Q(subject__icontains="schedule") |
    Q(subject__icontains="calendly") |
    Q(subject__icontains="meeting")
)

if user_email:
    potential_interviews = potential_interviews.exclude(sender__icontains=user_email)

print(f"\nMessages with interview keywords (not labeled 'interview_invite'): {potential_interviews.count()}")

if potential_interviews.exists():
    print("\nPotentially mislabeled interviews:")
    for msg in potential_interviews.order_by('-timestamp')[:10]:
        print(f"  • {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.company.name if msg.company else 'No Company'}")
        print(f"    Label: {msg.ml_label or 'UNLABELED'} | Subject: {msg.subject[:80]}")
        print()

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"\nDashboard shows:")
print(f"  • Applications This Week: Counting ml_label='job_application'")
print(f"  • Rejections This Week: Counting ml_label in ['rejected', 'rejection']")
print(f"  • Interviews This Week: Counting ml_label='interview_invite'")
print(f"\nIf counts don't match reality, messages may need to be relabeled.")
print(f"\nYou can relabel messages at: /label_messages/")
print(f"Or retrain the ML model with corrected labels.")
print("=" * 80)
