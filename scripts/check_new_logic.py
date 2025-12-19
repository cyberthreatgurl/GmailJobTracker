#!/usr/bin/env python3
"""Test updated applications_week logic using Message model."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message
from django.utils.timezone import now
from django.db.models import Q
from datetime import timedelta

week_cutoff = now() - timedelta(days=7)

print("=" * 80)
print("APPLICATIONS THIS WEEK - MESSAGE-BASED COUNT")
print("=" * 80)

# Replicate the updated logic from build_sidebar_context()
user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()

applications_week_qs = Message.objects.filter(
    ml_label__in=["job_application", "application"],
    timestamp__gte=week_cutoff,
    company__isnull=False,
)

print(f"\n1. job_application/application Messages since {week_cutoff}:")
print(f"   Total messages: {applications_week_qs.count()}")

# Exclude user's own messages
if user_email:
    before_count = applications_week_qs.count()
    applications_week_qs = applications_week_qs.exclude(sender__icontains=user_email)
    print(
        f"2. After excluding user email '{user_email}': {applications_week_qs.count()} (removed {before_count - applications_week_qs.count()})"
    )
else:
    print(f"2. No USER_EMAIL_ADDRESS set, skipping user exclusion")

# Exclude headhunter companies
before_count = applications_week_qs.count()
applications_week_qs = applications_week_qs.exclude(company__status="headhunter")
print(
    f"3. After excluding headhunter companies: {applications_week_qs.count()} (removed {before_count - applications_week_qs.count()})"
)

# Load headhunter domains and exclude
import json
from pathlib import Path

headhunter_domains = []
try:
    companies_path = Path("json/companies.json")
    if companies_path.exists():
        with open(companies_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            headhunter_domains = [
                d.strip().lower()
                for d in data.get("headhunter_domains", [])
                if d and isinstance(d, str)
            ]
except Exception:
    pass

if headhunter_domains:
    msg_hh_sender_q = Q()
    for d in headhunter_domains:
        msg_hh_sender_q |= Q(sender__icontains=f"@{d}")
    before_count = applications_week_qs.count()
    applications_week_qs = applications_week_qs.exclude(msg_hh_sender_q)
    print(
        f"4. After excluding headhunter domains: {applications_week_qs.count()} (removed {before_count - applications_week_qs.count()})"
    )
else:
    print(f"4. No headhunter domains found, skipping domain exclusion")

# Count distinct companies
applications_week = applications_week_qs.values("company_id").distinct().count()

print(f"\n{'=' * 80}")
print(f"FINAL COUNT: {applications_week} distinct companies")
print(f"{'=' * 80}")

# Show which companies
print("\nCompanies:")
for msg in applications_week_qs.order_by("company__name", "timestamp"):
    print(f"  - {msg.company.name:30} {msg.timestamp.date()} {msg.subject[:50]}")

print("\nDistinct company list:")
company_names = (
    applications_week_qs.values_list("company__name", flat=True)
    .distinct()
    .order_by("company__name")
)
for idx, name in enumerate(company_names, 1):
    count = applications_week_qs.filter(company__name=name).count()
    print(f"  {idx}. {name} ({count} messages)")

print(f"\n{'=' * 80}")
