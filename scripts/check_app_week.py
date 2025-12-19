#!/usr/bin/env python3
"""Quick diagnostic script to check Applications This Week count."""
import os
import sys

# Add parent directory to path so Django can be found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import ThreadTracking, Message, Company
from django.utils.timezone import now
from django.db.models import Exists, OuterRef, Q
from datetime import timedelta

week_cutoff = (now() - timedelta(days=7)).date()

print("=" * 80)
print("APPLICATIONS THIS WEEK - DIAGNOSTIC")
print("=" * 80)

# Step 1: All ThreadTracking rows in last 7 days
all_threads = ThreadTracking.objects.filter(
    sent_date__gte=week_cutoff,
    company__isnull=False,
).order_by("sent_date")

print(f"\n1. ThreadTracking rows with sent_date >= {week_cutoff}:")
print(f"   Total: {all_threads.count()}")
for t in all_threads:
    print(
        f"   - {t.company.name:30} sent={t.sent_date} ml_label={t.ml_label or 'None':20} status={t.company.status}"
    )

# Step 2: Exclude noise
non_noise = all_threads.exclude(ml_label="noise")
print(f"\n2. After excluding noise ThreadTracking: {non_noise.count()}")

# Step 3: Exclude headhunter companies
non_hh = non_noise.exclude(company__status="headhunter")
print(f"3. After excluding headhunter companies: {non_hh.count()}")

# Step 4: Check has_job_app annotation
job_app_exists = Exists(
    Message.objects.filter(
        thread_id=OuterRef("thread_id"),
        ml_label__in=["job_application", "application"],
    )
)

annotated = non_hh.annotate(has_job_app=job_app_exists)
print(f"\n4. Checking has_job_app (job_application/application Message exists):")
for t in annotated:
    print(
        f"   - {t.company.name:30} thread={t.thread_id:20} has_job_app={t.has_job_app}"
    )

# Step 5: Final distinct company count
with_job_app = annotated.filter(has_job_app=True)
distinct_companies = with_job_app.values("company_id").distinct().count()

print(f"\n5. Threads with has_job_app=True: {with_job_app.count()}")
print(f"6. Distinct companies (final count): {distinct_companies}")

# Also show which companies
company_names = (
    with_job_app.values_list("company__name", flat=True)
    .distinct()
    .order_by("company__name")
)
print(f"\n   Companies counted:")
for name in company_names:
    count = with_job_app.filter(company__name=name).count()
    print(f"   - {name} ({count} threads)")

print("\n" + "=" * 80)
