"""Verify ghosted count implementation."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking
from django.db.models import Q

# Query for ghosted companies (same logic as view)
ghosted_companies_qs = (
    ThreadTracking.objects.filter(
        Q(status="ghosted") | Q(ml_label="ghosted"), company__isnull=False
    )
    .exclude(ml_label="noise")
    .select_related("company")
    .values("company_id", "company__name", "sent_date")
    .order_by("-sent_date")
)

print(f"Total ghosted ThreadTracking records: {ghosted_companies_qs.count()}")

# Get unique companies
seen = set()
unique_companies = []
for item in ghosted_companies_qs:
    cid = item.get("company_id")
    cname = item.get("company__name")
    if cid is not None and cid not in seen and cname:
        unique_companies.append({"id": cid, "name": cname})
        seen.add(cid)

unique_companies.sort(key=lambda x: (x["name"] or "").lower())

print(f"\nUnique ghosted companies: {len(unique_companies)}")
print("\nFirst 10 ghosted companies:")
for c in unique_companies[:10]:
    print(f"  - {c['name']} (id={c['id']})")

print(f"\n✅ Ghosted count for dashboard card: {len(unique_companies)}")
