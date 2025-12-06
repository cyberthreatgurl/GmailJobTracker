#!/usr/bin/env python3
"""
Clean up empty companies (no messages or threads)

Usage:
    python cleanup_empty_companies.py [--dry-run] [--keep-recent] [--min-age-days N]
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from django.db import transaction
from django.utils.timezone import now
from tracker.models import Company, Message, ThreadTracking


def cleanup_empty_companies(dry_run=True, keep_recent=True, min_age_days=7):
    """
    Remove companies with no messages or threads.

    Args:
        dry_run: If True, only report what would be deleted
        keep_recent: If True, keep companies created recently
        min_age_days: Minimum age in days before a company can be deleted
    """
    print(f"{'=' * 80}")
    print("EMPTY COMPANY CLEANUP")
    print(f"{'=' * 80}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'APPLY CHANGES'}")
    print(f"Keep Recent: {keep_recent}")
    print(f"Min Age: {min_age_days} days")
    print()

    # Find companies with no messages or threads
    empty_companies = []
    cutoff_date = now() - timedelta(days=min_age_days)

    for company in Company.objects.all():
        msg_count = Message.objects.filter(company=company).count()
        thread_count = ThreadTracking.objects.filter(company=company).count()

        if msg_count == 0 and thread_count == 0:
            # Check age if keep_recent is enabled
            if keep_recent and company.first_contact > cutoff_date:
                continue

            empty_companies.append(
                {
                    "id": company.id,
                    "name": company.name,
                    "domain": company.domain,
                    "status": company.status,
                    "first_contact": company.first_contact,
                    "last_contact": company.last_contact,
                }
            )

    if not empty_companies:
        print("✅ No empty companies found to clean up.")
        return

    print(f"Found {len(empty_companies)} empty companies:\n")
    for idx, company in enumerate(empty_companies, 1):
        print(f"{idx:3}. ID {company['id']:4} - {company['name']}")
        print(f"     Domain: {company['domain']}")
        print(f"     Status: {company['status']}")
        print(f"     First Contact: {company['first_contact']}")
        print()

    if dry_run:
        print(f"\n⚠️  DRY RUN: Would delete {len(empty_companies)} companies")
        print("Run with --apply to actually delete these companies")
    else:
        print(f"\n⚠️  About to delete {len(empty_companies)} companies...")
        response = input("Continue? (yes/no): ")

        if response.lower() != "yes":
            print("❌ Cancelled by user")
            return

        try:
            with transaction.atomic():
                company_ids = [c["id"] for c in empty_companies]
                deleted_count = Company.objects.filter(id__in=company_ids).delete()[0]
                print(f"✅ Deleted {deleted_count} empty companies")

        except Exception as e:
            print(f"❌ Error deleting companies: {e}")
            sys.exit(1)

    print(f"\n{'=' * 80}\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Clean up empty companies")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete companies (default is dry-run)",
    )
    parser.add_argument(
        "--keep-recent",
        action="store_true",
        default=True,
        help="Keep companies created recently (default: True)",
    )
    parser.add_argument(
        "--min-age-days",
        type=int,
        default=7,
        help="Minimum age in days before deletion (default: 7)",
    )

    args = parser.parse_args()

    cleanup_empty_companies(
        dry_run=not args.apply,
        keep_recent=args.keep_recent,
        min_age_days=args.min_age_days,
    )


if __name__ == "__main__":
    main()
