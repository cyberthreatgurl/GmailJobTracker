#!/usr/bin/env python
"""
Normalize all CareFirst company references in Application and Message tables to canonical CareFirst (ID 326)
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message

# Canonical CareFirst company
canonical = Company.objects.get(id=326)

# All known CareFirst variants (expand as needed)
carefirst_variants = [
    "CareFirst or one of its subsidiary companies",
    "CareFirst",
    "carefirst",
    "Carefirst",
    "CareFirst BlueCross BlueShield",
]

# Update Applications
apps = ThreadTracking.objects.filter(company__name__in=carefirst_variants).exclude(
    company=canonical
)
print(f"Found {apps.count()} Application(s) with non-canonical CareFirst company")
for app in apps:
    print(f"  - App {app.id}: {app.company.name} -> CareFirst")
    app.company = canonical
    app.company_source = "normalized"
    app.save()
print("✅ Applications updated")

# Update Messages
msgs = Message.objects.filter(company__name__in=carefirst_variants).exclude(
    company=canonical
)
print(f"Found {msgs.count()} Message(s) with non-canonical CareFirst company")
for msg in msgs:
    print(f"  - Msg {msg.id}: {msg.company.name} -> CareFirst")
    msg.company = canonical
    msg.company_source = "normalized"
    msg.save()
print("✅ Messages updated")

print("\nDone! All CareFirst references are now normalized.")

