#!/usr/bin/env python
"""
Find and relabel the prescription message that was mislabeled.
Run with: python find_prescription_message.py
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
from django.db.models import Q

print("=" * 80)
print("FINDING PRESCRIPTION MESSAGE")
print("=" * 80)

# Search for messages containing "prescription"
prescription_messages = Message.objects.filter(
    Q(subject__icontains="prescription") | Q(body__icontains="prescription")
).order_by("-timestamp")

print(f"\nFound {prescription_messages.count()} messages containing 'prescription':\n")

for i, msg in enumerate(prescription_messages[:20], 1):  # Limit to first 20
    print(f"{i}. ID: {msg.id} | Timestamp: {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Label: {msg.ml_label or 'UNLABELED'} | Reviewed: {msg.reviewed}")
    print(f"   Company: {msg.company.name if msg.company else 'No Company'}")
    print(f"   Sender: {msg.sender}")
    print(f"   Subject: {msg.subject[:80]}")
    print()

# Focus on those labeled incorrectly (not 'noise')
incorrect = prescription_messages.exclude(ml_label="noise")

if incorrect.exists():
    print("=" * 80)
    print(f"MISLABELED PRESCRIPTION MESSAGES: {incorrect.count()}")
    print("=" * 80)

    for msg in incorrect:
        print(f"\n• ID: {msg.id} | Current Label: {msg.ml_label or 'UNLABELED'}")
        print(f"  {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.sender}")
        print(f"  Subject: {msg.subject[:60]}...")

    print("\n" + "=" * 80)
    response = input("\nRelabel these messages to 'noise'? (y/n): ").strip().lower()

    if response == "y":
        count = 0
        for msg in incorrect:
            msg.ml_label = "noise"
            msg.reviewed = True
            msg.save()
            print(f"✓ Relabeled message {msg.id}: {msg.subject[:40]}...")
            count += 1

        print(f"\n✅ Successfully relabeled {count} messages to 'noise'!")
        print("\n💡 Refresh your dashboard to see the updated statistics.")
    else:
        print("\n❌ No changes made.")
else:
    print("=" * 80)
    print("✅ All prescription messages are already labeled as 'noise'!")
    print("=" * 80)
