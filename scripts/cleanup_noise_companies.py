#!/usr/bin/env python
"""
Clean up noise messages by setting their company to None.

Noise messages should not be associated with any company, as they are
not relevant job-hunting communications (headhunters, spam, notifications, etc.).
"""
import os
import sys

import django

# Add parent directory to path so we can import Django modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

# Find all noise messages with companies
noise_with_company = Message.objects.filter(ml_label="noise").exclude(
    company__isnull=True
)

total = noise_with_company.count()
print(f"Found {total} noise messages with companies assigned.")

if total > 0:
    print("\nExamples:")
    for msg in noise_with_company[:5]:
        print(f"  - {msg.company.name if msg.company else 'None'}: {msg.subject[:60]}")

    print(f"\nSetting company=None for all {total} noise messages...")

    # Update all noise messages to have company=None
    updated = noise_with_company.update(
        company=None, company_source=""  # Also clear the source
    )

    print(f"✓ Updated {updated} noise messages")
    print("✓ Noise messages are now disassociated from companies")
else:
    print("✓ No noise messages have companies. Database is already clean!")
