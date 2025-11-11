"""
Management command to find and delete newsletter/bulk mail messages from the database.
Uses header analysis to identify messages that should have been ignored.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from tracker.models import Message, ThreadTracking
from parser import extract_metadata
from gmail_auth import get_gmail_service


class Command(BaseCommand):
    help = "Find and delete newsletter/bulk mail messages using header analysis"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of messages to check (default: all)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of messages to process per Gmail API batch (default: 100)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        batch_size = options["batch_size"]

        self.stdout.write(self.style.WARNING("\n=== Newsletter/Bulk Mail Cleanup ===\n"))

        if dry_run:
            self.stdout.write(self.style.NOTICE("DRY RUN MODE - No changes will be made\n"))

        # Get Gmail service
        try:
            service = get_gmail_service()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to authenticate with Gmail: {e}"))
            return

        # Get all messages from database
        messages = Message.objects.all().order_by("-timestamp")
        if limit:
            messages = messages[:limit]

        total_count = messages.count()
        self.stdout.write(f"Checking {total_count} messages...\n")

        newsletter_messages = []
        checked_count = 0
        error_count = 0

        # Process in batches to avoid rate limits
        for i in range(0, total_count, batch_size):
            batch = list(messages[i : i + batch_size])
            self.stdout.write(f"Processing batch {i // batch_size + 1} ({i + 1}-{i + len(batch)} of {total_count})...")

            for msg in batch:
                checked_count += 1

                try:
                    # Extract metadata with header hints (calls Gmail API internally)
                    metadata = extract_metadata(service, msg.msg_id)
                    header_hints = metadata.get("header_hints", {})

                    # Check if this is newsletter/bulk mail
                    is_newsletter = header_hints.get("is_newsletter", False)
                    is_bulk = header_hints.get("is_bulk", False)
                    is_noreply = header_hints.get("is_noreply", False)

                    if is_newsletter or (is_bulk and is_noreply):
                        newsletter_messages.append({
                            "msg": msg,
                            "is_newsletter": is_newsletter,
                            "is_bulk": is_bulk,
                            "is_noreply": is_noreply,
                            "header_hints": header_hints,
                        })

                        reason_parts = []
                        if is_newsletter:
                            reason_parts.append("newsletter")
                        if is_bulk:
                            reason_parts.append("bulk")
                        if is_noreply:
                            reason_parts.append("noreply")
                        reason = " + ".join(reason_parts)

                        self.stdout.write(
                            f"  ✓ Found: {msg.subject[:60]} ({reason})"
                        )

                except Exception as e:
                    error_count += 1
                    error_str = str(e)
                    
                    # Provide user-friendly error messages
                    if "Invalid id value" in error_str or "404" in error_str:
                        self.stdout.write(
                            self.style.WARNING(f"  ⊗ Skipped {msg.msg_id}: Message deleted by user or no longer exists in Gmail")
                        )
                    else:
                        self.stdout.write(
                            self.style.ERROR(f"  ✗ Error checking {msg.msg_id}: {e}")
                        )
                    continue

            # Progress update
            if (i + batch_size) % 500 == 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nProgress: {checked_count}/{total_count} checked, "
                        f"{len(newsletter_messages)} newsletters found, "
                        f"{error_count} errors\n"
                    )
                )

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== Summary ===\n"
                f"Total messages checked: {checked_count}\n"
                f"Newsletter/bulk messages found: {len(newsletter_messages)}\n"
                f"Errors: {error_count}\n"
            )
        )

        if not newsletter_messages:
            self.stdout.write(self.style.SUCCESS("No newsletter/bulk messages to clean up!"))
            return

        # Show details
        self.stdout.write("\n=== Messages to Delete ===\n")
        for item in newsletter_messages:
            msg = item["msg"]
            self.stdout.write(
                f"\nSubject: {msg.subject}\n"
                f"  Sender: {msg.sender if hasattr(msg, 'sender') else 'N/A'}\n"
                f"  Date: {msg.timestamp}\n"
                f"  Newsletter: {item['is_newsletter']}\n"
                f"  Bulk: {item['is_bulk']}\n"
                f"  No-Reply: {item['is_noreply']}\n"
            )

        # Delete if not dry run
        if not dry_run:
            self.stdout.write("\n")
            confirm = input(
                f"Delete {len(newsletter_messages)} newsletter/bulk messages? (yes/no): "
            )

            if confirm.lower() != "yes":
                self.stdout.write(self.style.WARNING("Aborted - no changes made"))
                return

            deleted_count = 0
            thread_deleted_count = 0

            with transaction.atomic():
                for item in newsletter_messages:
                    msg = item["msg"]

                    # Delete associated ThreadTracking entries
                    thread_count = ThreadTracking.objects.filter(
                        thread_id=msg.thread_id
                    ).count()
                    if thread_count > 0:
                        ThreadTracking.objects.filter(thread_id=msg.thread_id).delete()
                        thread_deleted_count += thread_count
                        self.stdout.write(
                            f"  Deleted {thread_count} ThreadTracking entries for {msg.subject[:60]}"
                        )

                    # Delete message
                    msg.delete()
                    deleted_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n=== Cleanup Complete ===\n"
                    f"Messages deleted: {deleted_count}\n"
                    f"ThreadTracking entries deleted: {thread_deleted_count}\n"
                )
            )
        else:
            self.stdout.write(
                self.style.NOTICE(
                    f"\nDRY RUN: Would delete {len(newsletter_messages)} messages "
                    f"(run without --dry-run to execute)"
                )
            )
