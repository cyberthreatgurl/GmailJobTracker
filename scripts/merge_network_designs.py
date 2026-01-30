#!/usr/bin/env python
"""Merge duplicate Network Designs companies."""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message, ThreadTracking

# Find both companies
canonical = Company.objects.filter(name="Network Designs, Inc.").first()
dup = Company.objects.filter(name="Network Designs Inc").first()

if canonical and dup:
    print(f"Canonical: {canonical.name} (ID={canonical.id})")
    print(f"Duplicate: {dup.name} (ID={dup.id})")
    
    # Move all messages to canonical
    msg_count = Message.objects.filter(company=dup).update(company=canonical)
    print(f"Moved {msg_count} messages to canonical company")
    
    # Move all thread tracking to canonical
    tt_count = ThreadTracking.objects.filter(company=dup).update(company=canonical)
    print(f"Moved {tt_count} thread trackings to canonical company")
    
    # Delete duplicate
    dup.delete()
    print("Deleted duplicate company")
elif canonical:
    print(f"Only canonical exists: {canonical.name} (ID={canonical.id})")
    print("No duplicate to merge.")
elif dup:
    print(f"Only duplicate exists: {dup.name} (ID={dup.id})")
    print("No canonical to merge into.")
else:
    print("Neither company found")
