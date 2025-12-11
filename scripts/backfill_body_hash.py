#!/usr/bin/env python
"""
Backfill body_hash field for existing Message records.

Usage:
    python scripts/backfill_body_hash.py           # Dry run (no changes)
    python scripts/backfill_body_hash.py --confirm # Apply changes
"""

import os
import sys
import re
import hashlib
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message


def normalize_body(body):
    """Normalize body text for consistent hashing."""
    if not body:
        return ""
    return re.sub(r'\s+', ' ', body).strip()


def compute_body_hash(body):
    """Compute SHA256 hash of normalized body."""
    normalized = normalize_body(body)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backfill body_hash for existing messages")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually update the database (default is dry run)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of records to process in each batch (default: 500)"
    )
    args = parser.parse_args()

    # Get messages with null body_hash
    messages_needing_hash = Message.objects.filter(body_hash__isnull=True)
    total_count = messages_needing_hash.count()

    if total_count == 0:
        print("✅ All messages already have body_hash populated.")
        return

    print(f"📊 Found {total_count} messages without body_hash")
    
    if not args.confirm:
        print("🔍 DRY RUN MODE - no changes will be made")
        print("   Run with --confirm to apply changes")
    else:
        print("✍️  UPDATING DATABASE")
    
    print()

    # Process in batches
    updated_count = 0
    batch_num = 0
    
    while True:
        # Get next batch
        batch = list(messages_needing_hash[:args.batch_size])
        if not batch:
            break
        
        batch_num += 1
        print(f"Processing batch {batch_num} ({len(batch)} messages)...", end=" ")
        
        if args.confirm:
            # Update each message in batch
            for msg in batch:
                msg.body_hash = compute_body_hash(msg.body)
                msg.save(update_fields=['body_hash'])
            
            updated_count += len(batch)
            print(f"✅ Updated {updated_count}/{total_count}")
        else:
            # Dry run - just show what would be updated
            for msg in batch[:3]:  # Show first 3 as examples
                body_hash = compute_body_hash(msg.body)
                print(f"\n   - Message {msg.id}: {msg.subject[:50]}...")
                print(f"     Hash: {body_hash[:16]}...")
            
            if len(batch) > 3:
                print(f"\n   ... and {len(batch) - 3} more in this batch")
            
            updated_count += len(batch)
            print(f"   Would update {updated_count}/{total_count}")
            break  # Only show one batch in dry run
    
    print()
    if args.confirm:
        print(f"✅ Successfully backfilled body_hash for {updated_count} messages")
    else:
        print(f"🔍 DRY RUN: Would backfill {total_count} messages")
        print("   Run with --confirm to apply changes")


if __name__ == "__main__":
    main()
