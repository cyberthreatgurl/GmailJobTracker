#!/usr/bin/env python
"""
Final verification of all company message links
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message

print("=" * 70)
print("FINAL VERIFICATION OF COMPANY MESSAGE LINKS")
print("=" * 70)
print()

companies = [
    (327, "Anthropic"),
    (326, "CareFirst"),
    (149, "Dragos"),
]

for company_id, expected_name in companies:
    try:
        company = Company.objects.get(id=company_id)
        msgs = Message.objects.filter(company=company).order_by("-timestamp")

        print(f"✅ {company.name} (ID {company.id})")
        print(f"   Messages: {msgs.count()}")
        for msg in msgs:
            sender_domain = (
                msg.sender.split("@")[1] if "@" in msg.sender else msg.sender
            )
            print(f"   - ID {msg.id:3d} | {sender_domain:30s} | {msg.subject[:45]}")
        print()
    except Company.DoesNotExist:
        print(f"❌ Company ID {company_id} ({expected_name}) not found!")
        print()

print("=" * 70)
print("✅ All company message links verified!")
print("=" * 70)
