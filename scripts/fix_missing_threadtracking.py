#!/usr/bin/env python
"""
Fix companies with missing ThreadTracking records.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking, Company

# Companies with mismatches
companies_to_fix = [
    (119, "Google", 7, 5),
    (98, "ECS", 3, 2),
    (40, "Palo Alto Networks", 2, 1),
    (129, "OPS Consulting", 2, 1),
]

print("Fixing companies with missing ThreadTracking records...")
print()

for company_id, company_name, expected_msg, current_tt in companies_to_fix:
    print(f"Processing {company_name} (ID={company_id})...")
    
    # Get all job_application messages for this company
    messages = Message.objects.filter(
        company_id=company_id,
        ml_label="job_application"
    ).order_by("-timestamp")
    
    print(f"  Found {messages.count()} job_application messages")
    
    created_count = 0
    exists_count = 0
    
    for msg in messages:
        # Check if ThreadTracking exists
        tt_exists = ThreadTracking.objects.filter(thread_id=msg.thread_id).exists()
        
        if tt_exists:
            exists_count += 1
            # Make sure ml_label is correct
            tt = ThreadTracking.objects.get(thread_id=msg.thread_id)
            if tt.ml_label != "job_application":
                old_label = tt.ml_label
                tt.ml_label = "job_application"
                tt.save(update_fields=["ml_label"])
                print(f"    Updated TT label: {old_label} → job_application")
        else:
            # Create ThreadTracking
            company = Company.objects.get(id=company_id)
            tt = ThreadTracking.objects.create(
                thread_id=msg.thread_id,
                company=company,
                sent_date=msg.timestamp.date() if msg.timestamp else None,
                ml_label="job_application",
                job_title=msg.subject,
            )
            created_count += 1
            print(f"    ✅ Created ThreadTracking for {msg.subject[:50]}...")
    
    print(f"  Created: {created_count}, Already existed: {exists_count}")
    print()

print("✅ All fixes applied!")
