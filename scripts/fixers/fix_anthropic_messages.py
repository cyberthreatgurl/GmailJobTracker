#!/usr/bin/env python
"""
Fix messages incorrectly pointing to company "rejection" (ID 35)
and point them to the correct Anthropic company (ID 327)
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message

# Get the companies
anthropic = Company.objects.get(id=327)
bad_company = Company.objects.get(id=35)

print(f'Bad company: ID={bad_company.id}, Name="{bad_company.name}"')
print(f'Correct company: ID={anthropic.id}, Name="{anthropic.name}"')
print()

# Find messages pointing to bad company
msgs = Message.objects.filter(company=bad_company)
print(
    f'Found {msgs.count()} messages pointing to company "{bad_company.name}" (ID {bad_company.id})'
)
print()

# Update each message
for msg in msgs:
    print(f"Updating message {msg.id}: {msg.subject[:60]}...")
    msg.company = anthropic
    msg.company_source = "manual_fix"  # Mark that this was manually corrected
    msg.save()

print()
print(f"✅ All messages updated to point to Anthropic (ID {anthropic.id})")

# Check if there are applications pointing to bad company
from tracker.models import ThreadTracking

apps = ThreadTracking.objects.filter(company=bad_company)
if apps.exists():
    print(
        f'\n⚠️  Also found {apps.count()} applications pointing to company "{bad_company.name}"'
    )
    for app in apps:
        print(f'Updating application {app.id}: {app.job_title or "No title"}')
        app.company = anthropic
        app.company_source = "manual_fix"
        app.save()
    print(f"✅ All applications updated to point to Anthropic")

print()
print("Done! You can now view the messages on the label companies page.")

