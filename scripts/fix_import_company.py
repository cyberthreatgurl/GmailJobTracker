"""
Re-ingest messages that were incorrectly parsed with company name "Import".

This script:
1. Finds all messages with company="Import"
2. Extracts their Gmail message IDs
3. Re-ingests each message using the updated parser logic
4. Reports success/failure for each message

Usage:
    python scripts/fix_import_company.py [--dry-run] [--limit N]

Options:
    --dry-run    Show what would be done without actually re-ingesting
    --limit N    Only process first N messages (useful for testing)
"""

import os
import sys

import django

# Change to project root directory (scripts should be run from project root)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)
os.chdir(project_root)

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import argparse
from parser import ingest_message

from gmail_auth import get_gmail_service
from tracker.models import Company, Message


def main():
    parser = argparse.ArgumentParser(description='Fix messages with company="Import"')
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually re-ingesting",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process first N messages"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for each message",
    )
    args = parser.parse_args()

    # Find "Import" company
    import_company = Company.objects.filter(name="Import").first()
    if not import_company:
        print("❌ No company named 'Import' found in database.")
        return

    # Get all messages with this company
    messages = Message.objects.filter(company=import_company).order_by("-timestamp")
    total_count = messages.count()

    if args.limit:
        messages = messages[: args.limit]
        print(
            f"📊 Found {total_count} messages with company='Import', processing first {args.limit}"
        )
    else:
        print(f"📊 Found {total_count} messages with company='Import'")

    if total_count == 0:
        print("✅ No messages to fix!")
        return

    # Show sample of what will be processed
    print("\n📋 Sample messages to be re-ingested:")
    for msg in messages[:5]:
        print(f"  • {msg.timestamp.strftime('%Y-%m-%d')} | {msg.subject[:60]}")
    if total_count > 5:
        print(f"  ... and {total_count - 5} more")

    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made")
        print(f"\nTo actually fix these messages, run without --dry-run:")
        print(f"  python scripts/fix_import_company.py")
        return

    # Confirm before proceeding
    print(f"\n⚠️  This will re-ingest {len(messages)} messages.")
    response = input("Continue? (y/N): ")
    if response.lower() != "y":
        print("❌ Cancelled")
        return

    # Get Gmail service
    print("\n🔐 Authenticating with Gmail...")
    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"❌ Failed to authenticate with Gmail: {e}")
        return

    # Re-ingest each message
    print(f"\n🔄 Re-ingesting {len(messages)} messages...")
    success_count = 0
    error_count = 0
    results = []

    for i, msg in enumerate(messages, 1):
        msg_id = msg.msg_id
        subject = msg.subject

        try:
            # Note: ingest_message takes (service, msg_id) only; it internally updates existing records
            ingest_message(service, msg_id)

            # Refresh from DB to see updated company
            msg.refresh_from_db()
            new_company = msg.company.name if msg.company else "None"

            if new_company != "Import":
                success_count += 1
                status = "✅"
                results.append(
                    {
                        "msg_id": msg_id,
                        "subject": subject[:50],
                        "new_company": new_company,
                        "status": "success",
                    }
                )
                if args.verbose:
                    print(
                        f"{status} [{i}/{len(messages)}] {new_company:30} | {subject[:50]}"
                    )
            else:
                error_count += 1
                status = "⚠️"
                results.append(
                    {
                        "msg_id": msg_id,
                        "subject": subject[:50],
                        "new_company": new_company,
                        "status": "still_import",
                    }
                )
                if args.verbose:
                    print(
                        f"{status} [{i}/{len(messages)}] Still 'Import'    | {subject[:50]}"
                    )

        except Exception as e:
            error_count += 1
            results.append(
                {
                    "msg_id": msg_id,
                    "subject": subject[:50],
                    "error": str(e),
                    "status": "error",
                }
            )
            if args.verbose:
                print(f"❌ [{i}/{len(messages)}] Error: {e}")

        # Progress indicator every 10 messages
        if not args.verbose and i % 10 == 0:
            print(f"  Processed {i}/{len(messages)}...", end="\r")

    # Final summary
    print(f"\n\n{'='*70}")
    print(f"📊 SUMMARY")
    print(f"{'='*70}")
    print(f"✅ Successfully fixed: {success_count}")
    print(
        f"⚠️  Still 'Import':     {error_count - len([r for r in results if r['status'] == 'error'])}"
    )
    print(
        f"❌ Errors:             {len([r for r in results if r['status'] == 'error'])}"
    )
    print(f"{'='*70}")

    # Show detailed results for messages that are still "Import"
    still_import = [r for r in results if r["status"] == "still_import"]
    if still_import:
        print(f"\n⚠️  {len(still_import)} messages still have company='Import':")
        for r in still_import[:10]:
            print(f"  • {r['subject']}")
        if len(still_import) > 10:
            print(f"  ... and {len(still_import) - 10} more")

    # Show unique new companies
    new_companies = {}
    for r in results:
        if r["status"] == "success":
            company = r["new_company"]
            new_companies[company] = new_companies.get(company, 0) + 1

    if new_companies:
        print(f"\n✅ Messages re-assigned to:")
        for company, count in sorted(new_companies.items(), key=lambda x: -x[1])[:10]:
            print(f"  • {company}: {count} messages")


if __name__ == "__main__":
    main()
