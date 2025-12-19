#!/usr/bin/env python3
"""Reclassify previously ignored 'NSA Employment Processing Update' messages.

Dry-run by default. Finds messages or ignored messages whose subject contains
the exact phrase 'NSA Employment Processing Update' (case-insensitive).
If --apply is passed, re-ingests from Gmail so new rejection rule applies.

Usage:
  python scripts/reclassify_nsa_processing_update.py            # dry-run
  python scripts/reclassify_nsa_processing_update.py --apply    # perform re-ingest
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List

# Ensure project root is on sys.path so 'dashboard' and 'tracker' can import
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django  # noqa: E402

django.setup()

from tracker.models import Message, IgnoredMessage  # noqa: E402

TARGET_PHRASE = "NSA Employment Processing Update"


def find_candidate_messages():
    """Return list of Message IDs matching the target phrase (case-insensitive)."""
    return list(
        Message.objects.filter(subject__icontains=TARGET_PHRASE).values_list(
            "id", "msg_id"
        )
    )


def find_ignored_candidates():
    """Return list of IgnoredMessage msg_ids matching the target phrase."""
    return list(
        IgnoredMessage.objects.filter(subject__icontains=TARGET_PHRASE).values_list(
            "msg_id", flat=True
        )
    )


def reingest(gmail_ids: List[str]):
    from parser import ingest_message  # local import to avoid circulars
    from gmail_auth import get_gmail_service

    service = get_gmail_service()
    successes = 0
    failures = 0
    for g_id in gmail_ids:
        try:
            result = ingest_message(service, g_id)
            if result:
                successes += 1
            else:
                failures += 1
        except Exception as e:  # pylint: disable=broad-except
            print(f"[FAIL] {g_id}: {e}")
            failures += 1
    return successes, failures


def main():
    parser = argparse.ArgumentParser(
        description="Reclassify NSA Employment Processing Update messages"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Perform re-ingest (default is dry-run)"
    )
    args = parser.parse_args()

    print("== Reclassify NSA Employment Processing Update ==")
    print(f"Searching for subject contains: '{TARGET_PHRASE}'\n")

    msg_rows = find_candidate_messages()
    ignored_ids = find_ignored_candidates()

    if not msg_rows and not ignored_ids:
        print("No matching messages or ignored messages found.")
        sys.exit(0)

    # Collect Gmail IDs to re-ingest: from existing Message rows + ignored rows not already included
    gmail_ids = [row[1] for row in msg_rows]
    for g_id in ignored_ids:
        if g_id not in gmail_ids:
            gmail_ids.append(g_id)

    print(
        f"Found {len(msg_rows)} existing Message row(s) and {len(ignored_ids)} IgnoredMessage row(s)."
    )
    print(f"Total unique Gmail IDs to re-ingest: {len(gmail_ids)}\n")

    # Show a preview table
    print("Preview (first 10):")
    for idx, g_id in enumerate(gmail_ids[:10], start=1):
        print(f" {idx:2}. gmail_id={g_id}")

    if not args.apply:
        print("\nDRY-RUN: No changes made. Re-run with --apply to re-ingest.")
        sys.exit(0)

    print("\nApplying re-ingest...")
    successes, failures = reingest(gmail_ids)
    print(f"\nDone. Successes={successes} Failures={failures}")
    if successes > 0:
        print(
            "Re-ingested messages will now be classified with updated rejection rule."
        )


if __name__ == "__main__":
    main()
