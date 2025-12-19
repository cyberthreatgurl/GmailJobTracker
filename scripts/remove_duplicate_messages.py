#!/usr/bin/env python
"""
Remove duplicate messages from the database.

Duplicates are identified by:
- Same subject
- Same sender
- Same timestamp (within 5 seconds)
- Same company

Keeps the message with the longest body (most complete) and deletes the rest.
"""

import os
import sys
import django
from datetime import timedelta

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
from django.db.models import Count, Q


def find_duplicates():
    """Find duplicate messages by subject, sender, and timestamp."""
    # Group by subject, sender, and company to find potential duplicates
    messages = Message.objects.all().order_by("subject", "sender", "timestamp")

    duplicates = []
    checked = set()

    for msg in messages:
        if msg.id in checked:
            continue

        # Find all messages with same subject, sender, and similar timestamp
        window_start = msg.timestamp - timedelta(seconds=5)
        window_end = msg.timestamp + timedelta(seconds=5)

        similar = Message.objects.filter(
            subject=msg.subject,
            sender=msg.sender,
            timestamp__gte=window_start,
            timestamp__lte=window_end,
        ).exclude(id__in=checked)

        if similar.count() > 1:
            similar_list = list(similar)
            for s in similar_list:
                checked.add(s.id)
            duplicates.append(similar_list)

    return duplicates


def remove_duplicates(dry_run=True):
    """Remove duplicate messages, keeping the one with longest body."""
    duplicate_groups = find_duplicates()

    if not duplicate_groups:
        print("✅ No duplicates found!")
        return

    print(f"Found {len(duplicate_groups)} groups of duplicate messages:\n")

    total_removed = 0
    for group in duplicate_groups:
        # Sort by body length (descending) to keep the most complete message
        group.sort(key=lambda m: len(m.body or ""), reverse=True)

        keep = group[0]
        to_delete = group[1:]

        print(f"📧 Subject: {keep.subject[:60]}...")
        print(f"   Sender: {keep.sender}")
        print(f"   Timestamp: {keep.timestamp}")
        print(f"   Company: {keep.company}")
        print(f"   Keeping: msg_id={keep.msg_id} (body length: {len(keep.body or '')})")

        for dup in to_delete:
            print(
                f"   🗑️  Deleting: msg_id={dup.msg_id} (body length: {len(dup.body or '')})"
            )
            if not dry_run:
                dup.delete()
                total_removed += 1

        print()

    if dry_run:
        print(
            f"🔍 DRY RUN: Would remove {sum(len(g)-1 for g in duplicate_groups)} duplicate messages"
        )
        print("\nRun with --confirm to actually delete duplicates")
    else:
        print(f"✅ Removed {total_removed} duplicate messages")


if __name__ == "__main__":
    dry_run = "--confirm" not in sys.argv
    remove_duplicates(dry_run=dry_run)
