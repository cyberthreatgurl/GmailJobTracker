#!/usr/bin/env python3
"""Backfill classification_source for existing messages.

For messages created before the classification_source field was added,
this script infers the source based on:
- confidence = 1.0 → likely rule-based
- confidence < 1.0 → likely ML-based
- None → unknown (will be updated on next re-ingest)
"""

import os
import sys

# Setup Django
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message


def backfill_classification_source(dry_run=True):
    """Backfill classification_source for existing messages."""

    # Messages without classification_source
    messages = Message.objects.filter(classification_source__isnull=True)
    total = messages.count()

    print(f"Found {total} messages without classification_source")

    if total == 0:
        print("✓ All messages already have classification_source")
        return

    rule_count = 0
    ml_count = 0
    none_count = 0

    for msg in messages:
        if msg.ml_label is None:
            # No label, leave as None
            none_count += 1
            continue
        elif msg.confidence == 1.0:
            # High confidence of exactly 1.0 usually indicates rule-based
            new_source = "rule"
            rule_count += 1
        elif msg.confidence is not None and msg.confidence > 0:
            # Other confidence values indicate ML
            new_source = "ml"
            ml_count += 1
        else:
            # No confidence, leave as None
            new_source = None
            none_count += 1

        if new_source and not dry_run:
            msg.classification_source = new_source
            msg.save(update_fields=["classification_source"])

    print(f"\nBackfill summary:")
    print(f"  Rule-based: {rule_count}")
    print(f"  ML-based: {ml_count}")
    print(f"  Unknown: {none_count}")

    if dry_run:
        print(f"\n🔍 DRY RUN - no changes made. Run with --apply to update.")
    else:
        print(f"\n✅ Updated {rule_count + ml_count} messages")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill classification_source")
    parser.add_argument(
        "--apply", action="store_true", help="Apply changes (default: dry-run)"
    )
    args = parser.parse_args()

    backfill_classification_source(dry_run=not args.apply)
