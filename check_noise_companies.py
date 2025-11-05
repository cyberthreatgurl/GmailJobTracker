#!/usr/bin/env python
"""Check for noise messages with companies assigned."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

# Find noise messages with companies
noise_with_company = Message.objects.filter(ml_label="noise").exclude(
    company__isnull=True
)

print(f"Noise messages with companies: {noise_with_company.count()}")
print()

if noise_with_company.exists():
    print("First 10 examples:")
    for msg in noise_with_company[:10]:
        company_name = msg.company.name if msg.company else None
        print(f"  - ID: {msg.id}")
        print(f"    msg_id: {msg.msg_id}")
        print(f"    Company: {company_name}")
        print(f"    Subject: {msg.subject[:80]}")
        print(f"    Sender: {msg.sender}")
        print()

    # Ask user if they want to fix
    print(
        f"\nTotal: {noise_with_company.count()} noise messages have companies assigned."
    )
    print("These should have company=None according to the new rule.")
else:
    print("✓ No noise messages have companies assigned. Database is clean!")
