"""
General-purpose script to re-ingest messages for debugging company parsing.

This script allows you to:
1. Re-ingest messages by company name (e.g., all "Import" messages)
2. Re-ingest specific message IDs
3. Re-ingest messages from a specific sender domain
4. Re-ingest messages matching a subject pattern

Usage:
    # Re-ingest all messages from a specific company
    python scripts/reingest_messages.py --company "Import"

    # Re-ingest specific message IDs
    python scripts/reingest_messages.py --msg-ids abc123 def456

    # Re-ingest messages from a domain
    python scripts/reingest_messages.py --domain proofpoint.com

    # Re-ingest messages matching subject pattern
    python scripts/reingest_messages.py --subject-contains "application"

    # Dry run to see what would be re-ingested
    python scripts/reingest_messages.py --company "Import" --dry-run

    # Limit number of messages
    python scripts/reingest_messages.py --company "Import" --limit 10

Options:
    --company NAME           Re-ingest all messages from company NAME
    --msg-ids ID [ID ...]    Re-ingest specific Gmail message IDs
    --domain DOMAIN          Re-ingest messages from sender domain
    --subject-contains TEXT  Re-ingest messages with TEXT in subject
    --dry-run               Show what would be done without actually re-ingesting
    --limit N               Only process first N messages
    --verbose              Show detailed output for each message
    --show-changes         Show before/after company names
"""

import os
import sys

import django

# Change to project root directory (scripts should be run from project root)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)
os.chdir(project_root)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import argparse
from typing import List

from gmail_auth import get_gmail_service
from tracker.models import Company, Message, ThreadTracking


def get_messages_to_process(args) -> List[Message]:
    """Get messages based on command-line filters."""
    messages = Message.objects.all()

    if args.company:
        company = Company.objects.filter(name=args.company).first()
        if not company:
            print(f"❌ Company '{args.company}' not found")
            sys.exit(1)
        messages = messages.filter(company=company)
        print(f"🔍 Filtering by company: {args.company}")

    if args.msg_ids:
        messages = messages.filter(msg_id__in=args.msg_ids)
        print(f"🔍 Filtering by {len(args.msg_ids)} message ID(s)")

    if args.domain:
        messages = messages.filter(sender__icontains=f"@{args.domain}")
        print(f"🔍 Filtering by domain: {args.domain}")

    if args.subject_contains:
        messages = messages.filter(subject__icontains=args.subject_contains)
        print(f"🔍 Filtering by subject contains: '{args.subject_contains}'")

    # Order by newest first
    messages = messages.order_by("-timestamp")

    if args.limit:
        total = messages.count()
        messages = messages[: args.limit]
        print(f"📊 Found {total} messages, limiting to {args.limit}")

    return list(messages)


def show_message_preview(messages: List[Message], max_show: int = 10):
    """Show preview of messages to be processed."""
    print(f"\n📋 Messages to be re-ingested ({len(messages)} total):")
    for i, msg in enumerate(messages[:max_show], 1):
        company_name = msg.company.name if msg.company else "None"
        print(
            f"  {i:2}. {msg.timestamp.strftime('%Y-%m-%d')} | {company_name:20} | {msg.subject[:50]}"
        )

    if len(messages) > max_show:
        print(f"  ... and {len(messages) - max_show} more")


def reingest_messages(messages: List[Message], args):
    """Re-ingest the given messages."""
    print("\n🔐 Authenticating with Gmail...")
    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"❌ Failed to authenticate with Gmail: {e}")
        return

    # Import ingest_message lazily to avoid loading ML models during dry-run
    try:
        from parser import ingest_message
    except Exception as e:
        ingest_message = None
        print(f"⚠️ Warning: failed to import parser.ingest_message: {e}; live re-ingest will be skipped and fallback used where possible")

    print(f"\n🔄 Re-ingesting {len(messages)} messages...\n")

    results = {"success": [], "unchanged": [], "error": []}

    for i, msg in enumerate(messages, 1):
        msg_id = msg.msg_id
        old_company = msg.company.name if msg.company else "None"
        subject = msg.subject

        try:
            # Note: ingest_message takes (service, msg_id) only; it internally updates existing records
            if ingest_message is None:
                # Parser not importable (models missing/corrupt) — simulate error so fallback can run
                raise Exception("parser_import_failed")
            ingest_message(service, msg_id)

            # Refresh from DB to see updates
            msg.refresh_from_db()
            new_company = msg.company.name if msg.company else "None"

            if new_company != old_company:
                results["success"].append(
                    {
                        "msg_id": msg_id,
                        "subject": subject,
                        "old_company": old_company,
                        "new_company": new_company,
                    }
                )
                status = "✅ CHANGED"
                company_info = f"{old_company} → {new_company}"
            else:
                results["unchanged"].append(
                    {"msg_id": msg_id, "subject": subject, "company": old_company}
                )
                status = "⚪ SAME   "
                company_info = f"{old_company}"

            if args.verbose or args.show_changes:
                print(
                    f"{status} [{i:3}/{len(messages)}] {company_info:40} | {subject[:40]}"
                )
            elif i % 5 == 0:
                print(f"  Processed {i}/{len(messages)}...", end="\r")

        except Exception as e:
            # If Gmail returns a 404 (message not found), optionally create a ThreadTracking
            # from the existing Message in the DB as a fallback so the dashboard can
            # display the thread even when live fetch fails.
            errmsg = str(e)
            if (not args.no_fallback) and (
                "Requested entity was not found" in errmsg
                or "404" in errmsg
            ):
                # Attempt fallback creation from existing Message
                try:
                    tt, created = ThreadTracking.objects.get_or_create(
                        thread_id=msg.thread_id,
                        defaults={
                            'company': msg.company,
                            'company_source': msg.company_source or 'reingest_fallback',
                            'job_title': '',
                            'job_id': '',
                            'status': msg.ml_label or 'interview',
                            'sent_date': msg.timestamp.date() if msg.timestamp else None,
                            'rejection_date': None,
                            'interview_date': None,
                            'ml_label': msg.ml_label,
                            'ml_confidence': getattr(msg, 'confidence', None),
                            'reviewed': False,
                        },
                    )

                    if created:
                        results['success'].append(
                            {
                                'msg_id': msg_id,
                                'subject': subject,
                                'old_company': old_company,
                                'new_company': msg.company.name if msg.company else 'None',
                                'fallback_created': True,
                                'thread_id': tt.thread_id,
                            }
                        )
                        if args.verbose:
                            print(
                                f"⚠️ FALLBACK Created TT [{i:3}/{len(messages)}] thread={tt.thread_id} | {subject[:60]}"
                            )
                    else:
                        results['unchanged'].append(
                            {'msg_id': msg_id, 'subject': subject, 'company': old_company}
                        )
                        if args.verbose:
                            print(
                                f"ℹ️ FALLBACK existing TT [{i:3}/{len(messages)}] thread={tt.thread_id} | {subject[:60]}"
                            )
                    # continue to next message
                    continue
                except Exception as e2:
                    results["error"].append(
                        {"msg_id": msg_id, "subject": subject, "error": f"fallback failed: {e2}"}
                    )
                    if args.verbose:
                        print(f"❌ FALLBACK ERROR [{i:3}/{len(messages)}] {e2}")
                    continue

            # Otherwise record the original error
            results["error"].append(
                {"msg_id": msg_id, "subject": subject, "error": errmsg}
            )
            if args.verbose:
                print(f"❌ ERROR  [{i:3}/{len(messages)}] {errmsg[:80]}")

    return results


def print_summary(results: dict):
    """Print summary of re-ingestion results."""
    print(f"\n\n{'='*80}")
    print(f"📊 RE-INGESTION SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Changed:   {len(results['success'])} messages")
    print(f"⚪ Unchanged: {len(results['unchanged'])} messages")
    print(f"❌ Errors:    {len(results['error'])} messages")
    print(f"{'='*80}")

    # Show company changes
    if results["success"]:
        print(f"\n✅ Company changes ({len(results['success'])} messages):")

        # Group by old → new company
        changes = {}
        for r in results["success"]:
            key = f"{r['old_company']} → {r['new_company']}"
            if key not in changes:
                changes[key] = []
            changes[key].append(r["subject"][:60])

        for change, subjects in sorted(changes.items(), key=lambda x: -len(x[1]))[:10]:
            print(f"\n  {change} ({len(subjects)} messages):")
            for subj in subjects[:3]:
                print(f"    • {subj}")
            if len(subjects) > 3:
                print(f"    ... and {len(subjects) - 3} more")

    # Show errors
    if results["error"]:
        print(f"\n❌ Errors ({len(results['error'])} messages):")
        for r in results["error"][:10]:
            print(f"  • {r['subject'][:60]}")
            print(f"    Error: {r['error']}")
        if len(results["error"]) > 10:
            print(f"  ... and {len(results['error']) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Re-ingest Gmail messages for debugging company parsing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Filters
    parser.add_argument("--company", help="Re-ingest messages from this company")
    parser.add_argument(
        "--msg-ids", nargs="+", help="Re-ingest specific Gmail message IDs"
    )
    parser.add_argument("--domain", help="Re-ingest messages from this sender domain")
    parser.add_argument(
        "--subject-contains", help="Re-ingest messages with this text in subject"
    )

    # Options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without re-ingesting",
    )
    parser.add_argument("--limit", type=int, help="Only process first N messages")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for each message",
    )
    parser.add_argument(
        "--show-changes", action="store_true", help="Show before/after company names"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Do not create ThreadTracking fallback when Gmail fetch fails (default: create fallback)",
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.company, args.msg_ids, args.domain, args.subject_contains]):
        parser.error(
            "Must specify at least one filter: --company, --msg-ids, --domain, or --subject-contains"
        )

    # Get messages to process
    messages = get_messages_to_process(args)

    if not messages:
        print("❌ No messages found matching filters")
        return

    # Show preview
    show_message_preview(messages)

    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made")
        print(f"\nTo actually re-ingest, run without --dry-run")
        return

    # Confirm
    if not args.yes:
        print(f"\n⚠️  This will re-ingest {len(messages)} messages from Gmail.")
        response = input("Continue? (y/N): ")
        if response.lower() != "y":
            print("❌ Cancelled")
            return

    # Re-ingest
    results = reingest_messages(messages, args)

    # Print summary
    print_summary(results)


if __name__ == "__main__":
    main()
