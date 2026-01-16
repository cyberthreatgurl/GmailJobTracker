#!/usr/bin/env python
"""
Check what ml_labels the mismatched ThreadTracking records have.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Companies with mismatches
companies = {
    119: "Google",
    98: "ECS",
    40: "Palo Alto Networks",
    129: "OPS Consulting",
}

for company_id, company_name in companies.items():
    print(f"\n{company_name} (ID={company_id}):")
    print("=" * 60)
    
    # Get all job_application messages
    messages = Message.objects.filter(
        company_id=company_id,
        ml_label="job_application"
    ).order_by("-timestamp")
    
    for msg in messages:
        tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if tt:
            status = "✅" if tt.ml_label == "job_application" else f"❌ TT={tt.ml_label}"
            print(f"  {msg.timestamp.date()} | Msg=job_application | {status} | {msg.subject[:50]}...")
        else:
            print(f"  {msg.timestamp.date()} | Msg=job_application | ❌ NO TT | {msg.subject[:50]}...")
