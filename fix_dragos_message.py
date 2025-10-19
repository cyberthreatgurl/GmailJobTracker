#!/usr/bin/env python
"""
Fix message 79 to point to correct Dragos company
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message

# Get message 79
msg = Message.objects.get(id=79)

print(f"Message 79: {msg.subject}")
print(
    f"Current company: {msg.company.name if msg.company else None} (ID {msg.company.id if msg.company else None})"
)
print(f"Sender: {msg.sender}")
print()

# Find Dragos company
dragos_companies = Company.objects.filter(name__icontains="dragos")
print(f"Dragos companies found: {dragos_companies.count()}")
for c in dragos_companies:
    msg_count = Message.objects.filter(company=c).count()
    print(f'  - ID {c.id}: "{c.name}" ({msg_count} messages)')
print()

if dragos_companies.count() == 1:
    dragos = dragos_companies.first()
elif dragos_companies.count() > 1:
    # Use the one with the simplest name
    dragos = dragos_companies.filter(name="Dragos").first() or dragos_companies.first()
else:
    print("❌ No Dragos company found! Creating one...")
    dragos = Company.objects.create(name="Dragos", domain="dragos.com", confidence=0.95)
    print(f"✅ Created Dragos company (ID {dragos.id})")
    print()

# Update message
msg.company = dragos
msg.company_source = "manual_fix"
msg.save()

print(f'✅ Message {msg.id} updated to point to "{dragos.name}" (ID {dragos.id})')
print()

# Check if there are other messages from dragos.com
print("Checking for other messages from dragos.com sender...")
msgs_from_dragos = Message.objects.filter(sender__icontains="dragos.com")
print(f"Found {msgs_from_dragos.count()} messages from dragos.com senders")
for m in msgs_from_dragos:
    if m.company != dragos:
        print(
            f'  - Message {m.id}: "{m.subject[:50]}" -> currently points to {m.company.name if m.company else "None"}'
        )
        m.company = dragos
        m.company_source = "manual_fix"
        m.save()
        print(f"    ✅ Updated to Dragos")

print()
print("Done!")
