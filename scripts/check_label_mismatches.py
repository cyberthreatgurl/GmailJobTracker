#!/usr/bin/env python
"""
Check for mismatches between Message and ThreadTracking ml_label counts.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking, Company
from django.db.models import Count

# Find companies that have job_application Messages
# Count UNIQUE threads, not total messages (multiple messages can be in same thread)
companies_with_msg_raw = Message.objects.filter(ml_label="job_application").select_related("company")

# Group by company and count unique threads
from collections import defaultdict
company_thread_counts = defaultdict(set)
for msg in companies_with_msg_raw:
    if msg.company_id:
        company_thread_counts[msg.company_id].add(msg.thread_id)

# Convert to list sorted by count
companies_data = [
    {"company_id": cid, "unique_threads": len(threads)}
    for cid, threads in company_thread_counts.items()
]
companies_data.sort(key=lambda x: x["unique_threads"], reverse=True)

print(f"Companies with job_application messages: {len(companies_data)}")
print()

# Check if their ThreadTracking counts match
issues = []
for c in companies_data:
    company_id = c["company_id"]
    company = Company.objects.get(id=company_id)
    unique_threads = c["unique_threads"]

    # Count ThreadTracking with ml_label=job_application
    tt_count = ThreadTracking.objects.filter(
        company_id=company_id, ml_label="job_application"
    ).count()

    status = "✅" if unique_threads == tt_count else "❌ MISMATCH"
    print(f"{company.name:40} | Threads: {unique_threads:2} | ThreadTracking: {tt_count:2} | {status}")

    if unique_threads != tt_count:
        issues.append({"company": company.name, "id": company_id, "unique_threads": unique_threads, "tt_count": tt_count})

print()
print(f"Total issues found: {len(issues)}")

if issues:
    print()
    print("Companies with mismatches:")
    for issue in issues:
        print(f"  {issue['company']} (ID={issue['id']}): {issue['unique_threads']} unique threads but {issue['tt_count']} ThreadTracking")
