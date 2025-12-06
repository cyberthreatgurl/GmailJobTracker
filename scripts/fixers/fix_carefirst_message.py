#!/usr/bin/env python
"""
Fix message 80 to point to correct CareFirst company
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message

# Get message 80
msg = Message.objects.get(id=80)

# Get both CareFirst companies
c1 = Company.objects.get(id=57)
c2 = Company.objects.get(id=326)

print(f"Message 80: {msg.subject[:60]}")
print(
    f"Current company: {msg.company.name if msg.company else None} (ID {msg.company.id if msg.company else None})"
)
print(f"Sender: {msg.sender}")
print()

print(f'Company 57: "{c1.name}"')
print(f"  Messages: {Message.objects.filter(company=c1).count()}")
print(f'  Domain: {c1.domain or "(none)"}')
print()

print(f'Company 326: "{c2.name}"')
print(f"  Messages: {Message.objects.filter(company=c2).count()}")
print(f'  Domain: {c2.domain or "(none)"}')
print()

# Use the simpler name (ID 326: "CareFirst")
correct_company = c2
print(f'Using company ID {correct_company.id}: "{correct_company.name}"')
print()

# Update message
msg.company = correct_company
msg.company_source = "manual_fix"
msg.save()

print(
    f'✅ Message {msg.id} updated to point to "{correct_company.name}" (ID {correct_company.id})'
)
print()

# Check if there are other messages that should be moved
print("Checking for other messages from carefirst.com sender...")
msgs_from_carefirst = Message.objects.filter(sender__icontains="carefirst.com")
print(f"Found {msgs_from_carefirst.count()} messages from carefirst.com senders")
for m in msgs_from_carefirst:
    if m.company != correct_company:
        print(
            f'  - Message {m.id}: "{m.subject[:50]}" -> currently points to {m.company.name if m.company else "None"}'
        )
        m.company = correct_company
        m.company_source = "manual_fix"
        m.save()
        print(f"    ✅ Updated to CareFirst")

print()
print("Done!")
