"""
Management command to re-ingest messages and let the new auto-ignore logic handle newsletters.
This is safer than deletion and respects the existing ignore tracking system.
"""

from django.core.management.base import BaseCommand
from tracker.models import Message, IgnoredMessage
from parser import ingest_message, extract_metadata, is_application_related
from gmail_auth import get_gmail_service


class Command(BaseCommand):
    help = "Re-ingest messages to identify and mark newsletters/bulk mail as ignored"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be marked ignored without making changes",
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
            default=50,
            help="Number of messages to process per batch (default: 50)",
        )
        parser.add_argument(
            "--delete-marked",
            action="store_true",
            help="Delete messages from Message table after marking as ignored",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        batch_size = options["batch_size"]
        delete_marked = options["delete_marked"]

        self.stdout.write(self.style.WARNING("\n=== Newsletter/Bulk Mail Re-Ingestion ===\n"))

        if dry_run:
            self.stdout.write(self.style.NOTICE("DRY RUN MODE - No changes will be made\n"))

        # Get Gmail service
        try:
            service = get_gmail_service()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to authenticate with Gmail: {e}"))
            return

        # Get all messages from database (newest first to catch recent newsletters)
        messages = Message.objects.all().order_by("-timestamp")
        if limit:
            messages = messages[:limit]

        total_count = messages.count()
        self.stdout.write(f"Re-ingesting {total_count} messages to check for newsletters...\n")

        ignored_count = 0
        deleted_count = 0
        checked_count = 0
        error_count = 0
        already_ignored_count = 0

        # Process in batches
        for i in range(0, total_count, batch_size):
            batch = list(messages[i : i + batch_size])
            self.stdout.write(
                f"\nBatch {i // batch_size + 1} ({i + 1}-{i + len(batch)} of {total_count})..."
            )

            for msg in batch:
                checked_count += 1

                try:
                    # Check if already in IgnoredMessage
                    if IgnoredMessage.objects.filter(msg_id=msg.msg_id).exists():
                        already_ignored_count += 1
                        continue

                    # Extract metadata to check headers (calls Gmail API internally)
                    metadata = extract_metadata(service, msg.msg_id)
                    header_hints = metadata.get("header_hints", {})

                    is_newsletter = header_hints.get("is_newsletter", False)
                    is_bulk = header_hints.get("is_bulk", False)
                    is_noreply = header_hints.get("is_noreply", False)

                    # Check if this is application-related using patterns.json
                    # (ATS systems add List-Unsubscribe headers even to transactional emails)
                    is_app_related = is_application_related(
                        metadata["subject"],
                        metadata.get("body", "")[:500]
                    )

                    # Check if should be ignored (skip if application-related)
                    should_ignore = (not is_app_related) and (is_newsletter or (is_bulk and is_noreply))

                    if should_ignore:
                        reason_parts = []
                        if is_newsletter:
                            reason_parts.append("newsletter")
                        if is_bulk:
                            reason_parts.append("bulk")
                        if is_noreply:
                            reason_parts.append("noreply")
                        reason = " + ".join(reason_parts)

                        self.stdout.write(
                            f"  📧 Newsletter/bulk: {msg.subject[:60]} ({reason})"
                        )

                        if not dry_run:
                            # Re-ingest will trigger auto-ignore logic
                            result = ingest_message(service, msg.msg_id)

                            if result == "ignored":
                                ignored_count += 1

                                # Optionally delete from Message table
                                if delete_marked:
                                    Message.objects.filter(msg_id=msg.msg_id).delete()
                                    deleted_count += 1
                                    self.stdout.write(
                                        self.style.SUCCESS(
                                            f"    ✓ Marked ignored and deleted from Message table"
                                        )
                                    )
                                else:
                                    self.stdout.write(
                                        self.style.SUCCESS(f"    ✓ Marked ignored in IgnoredMessage")
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
                            self.style.ERROR(f"  ✗ Error processing {msg.msg_id}: {e}")
                        )
                    continue

            # Progress update
            if (i + batch_size) % 200 == 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nProgress: {checked_count}/{total_count} checked, "
                        f"{ignored_count} marked ignored, "
                        f"{already_ignored_count} already ignored, "
                        f"{error_count} errors\n"
                    )
                )

        # Final summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== Summary ===\n"
                f"Total messages checked: {checked_count}\n"
                f"Already in IgnoredMessage: {already_ignored_count}\n"
                f"Newly marked as ignored: {ignored_count}\n"
                f"Deleted from Message table: {deleted_count}\n"
                f"Errors: {error_count}\n"
            )
        )

        if dry_run and ignored_count > 0:
            self.stdout.write(
                self.style.NOTICE(
                    f"\nDRY RUN: Would mark {ignored_count} messages as ignored "
                    f"(run without --dry-run to execute)"
                )
            )

        if not dry_run and ignored_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ Cleanup complete! {ignored_count} newsletter/bulk messages now tracked in IgnoredMessage."
                )
            )

            if not delete_marked:
                self.stdout.write(
                    self.style.NOTICE(
                        f"\nNote: Messages still exist in Message table. "
                        f"Run with --delete-marked to remove them after verification."
                    )
                )
