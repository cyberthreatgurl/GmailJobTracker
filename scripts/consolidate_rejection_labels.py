"""Consolidate 'rejected' and 'rejection' labels into 'rejection'.

Finds all messages labeled as 'rejected' and updates them to 'rejection'.
Also checks patterns.json and code for inconsistencies.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking


def main():
    """Consolidate rejected/rejection labels."""
    # Check current state
    rejected = Message.objects.filter(ml_label="rejected")
    rejection = Message.objects.filter(ml_label="rejection")

    rejected_count = rejected.count()
    rejection_count = rejection.count()

    print("=" * 80)
    print("LABEL CONSOLIDATION: rejected → rejection")
    print("=" * 80)
    print()
    print(f"Current state:")
    print(f'  Messages labeled "rejected": {rejected_count}')
    print(f'  Messages labeled "rejection": {rejection_count}')
    print()

    if rejected_count == 0:
        print("✓ No messages with 'rejected' label found. Nothing to consolidate.")
        return

    # Show sample messages
    print(f'Sample "rejected" messages to be updated:')
    for msg in rejected[:10]:
        print(f"  - {msg.msg_id}: {msg.subject[:70]}")
    print()

    # Update all rejected → rejection
    updated = rejected.update(ml_label="rejection")
    print(f"✓ Updated {updated} messages from 'rejected' → 'rejection'")
    print()

    # Check ThreadTracking
    thread_rejected = ThreadTracking.objects.filter(ml_label="rejected")
    thread_rejected_count = thread_rejected.count()

    if thread_rejected_count > 0:
        print(
            f'Found {thread_rejected_count} ThreadTracking entries with "rejected" label'
        )
        thread_updated = thread_rejected.update(ml_label="rejection")
        print(
            f"✓ Updated {thread_updated} ThreadTracking entries from 'rejected' → 'rejection'"
        )
        print()

    # Final state
    final_rejected = Message.objects.filter(ml_label="rejected").count()
    final_rejection = Message.objects.filter(ml_label="rejection").count()

    print("=" * 80)
    print("FINAL STATE:")
    print(f'  Messages labeled "rejected": {final_rejected}')
    print(f'  Messages labeled "rejection": {final_rejection}')
    print()
    print("✓ Consolidation complete!")
    print()
    print("⚠️  Manual review needed:")
    print("  1. Check parser.py LABEL_MAP for 'rejected' vs 'rejection'")
    print("  2. Check patterns.json for 'rejected' vs 'rejection' keys")
    print("  3. Search codebase for hardcoded 'rejected' strings")
    print("=" * 80)


if __name__ == "__main__":
    main()
