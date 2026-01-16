#!/usr/bin/env python
"""Check manual entries for Wireless Research Group."""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, ThreadTracking, Message

# Search for Wireless Research Group
print("Searching for 'Wireless Research' companies...")
companies = Company.objects.filter(name__icontains="Wireless Research")
print(f"Found: {companies.count()}")
for c in companies:
    print(f"  {c.name} (ID={c.id})")
print()

# Check ThreadTracking with company_source='manual'
print("Recent manual ThreadTracking entries (last 10):")
manual_threads = ThreadTracking.objects.filter(company_source="manual").order_by("-sent_date")[:10]
print(f"Count: {manual_threads.count()}")
for tt in manual_threads:
    company_name = tt.company.name if tt.company else "(None)"
    print(f"  {tt.sent_date} | Company: {company_name} (ID={tt.company_id}) | {tt.job_title}")
print()

# Check Messages with company_source='manual'
print("Recent manual Message entries (last 10):")
manual_msgs = Message.objects.filter(company_source="manual").order_by("-timestamp")[:10]
print(f"Count: {manual_msgs.count()}")
for m in manual_msgs:
    company_name = m.company.name if m.company else "(None)"
    print(f"  {m.timestamp.date()} | Company: {company_name} (ID={m.company_id}) | {m.subject}")
