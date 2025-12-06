#!/usr/bin/env python
"""
Show unreviewed noise messages with companies for inspection.

This helps during model training/testing to see which messages
were classified as noise but still have company associations.
"""
import os
import sys

import django

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

# Find unreviewed noise messages with companies
unreviewed_noise = (
    Message.objects.filter(ml_label="noise", reviewed=False)
    .exclude(company__isnull=True)
    .order_by("-confidence")
)

total = unreviewed_noise.count()
print(f"\n{'='*80}")
print(f"UNREVIEWED NOISE MESSAGES WITH COMPANIES: {total}")
print(f"{'='*80}\n")

if total > 0:
    print("These messages keep their companies until reviewed (for inspection):\n")

    for i, msg in enumerate(unreviewed_noise[:20], 1):
        company_name = msg.company.name if msg.company else "None"
        print(f"{i}. [{msg.confidence:.2%}] {company_name}")
        print(f"   Subject: {msg.subject[:70]}")
        print(f"   Sender: {msg.sender}")
        print(f"   msg_id: {msg.msg_id}")
        print()

    if total > 20:
        print(f"... and {total - 20} more")

    print(f"\nTo clear companies for these messages:")
    print(f"1. Review them in Django admin")
    print(f"2. Mark 'reviewed=True' for confirmed noise messages")
    print(f"3. Companies will be automatically cleared on save")
else:
    print("✓ No unreviewed noise messages with companies")
    print("  Either all are reviewed, or none were classified as noise yet")
