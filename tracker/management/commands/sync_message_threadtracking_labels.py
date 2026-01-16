"""
Management command to sync ThreadTracking ml_label with Message ml_label.

This fixes cases where:
- Message has ml_label='job_application'
- But ThreadTracking has ml_label='ghosted' or other label
- Causing applications to not appear in Application Details section

Usage:
    python manage.py sync_message_threadtracking_labels [--dry-run]
"""

from django.core.management.base import BaseCommand
from tracker.models import Message, ThreadTracking


class Command(BaseCommand):
    help = "Sync ThreadTracking ml_label to match Message ml_label for job applications"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("🔍 DRY RUN MODE - No changes will be made"))
            self.stdout.write("")

        # Find all job_application messages
        job_app_messages = Message.objects.filter(ml_label="job_application").select_related("company")

        self.stdout.write(f"Found {job_app_messages.count()} job_application messages")
        self.stdout.write("")

        # Track statistics
        mismatches = []
        already_correct = 0
        missing_tt = 0

        # Check each message's ThreadTracking
        for msg in job_app_messages:
            tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()

            if not tt:
                missing_tt += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"❌ No ThreadTracking for thread {msg.thread_id[:20]}... "
                        f"({msg.company.name if msg.company else 'No company'})"
                    )
                )
                continue

            if tt.ml_label != "job_application":
                company_name = msg.company.name if msg.company else "No company"
                mismatches.append(
                    {
                        "thread_id": msg.thread_id,
                        "company": company_name,
                        "old_label": tt.ml_label,
                        "new_label": "job_application",
                        "tt_obj": tt,
                    }
                )
            else:
                already_correct += 1

        # Report findings
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Already correct: {already_correct}")
        self.stdout.write(f"Mismatches found: {len(mismatches)}")
        self.stdout.write(f"Missing ThreadTracking: {missing_tt}")
        self.stdout.write("=" * 60)
        self.stdout.write("")

        if len(mismatches) == 0:
            self.stdout.write(self.style.SUCCESS("✅ No mismatches found - all labels are synchronized!"))
            return

        # Show mismatches
        self.stdout.write("Mismatches to fix:")
        for m in mismatches:
            self.stdout.write(
                f"  {m['company']:35} | {m['old_label']:15} → job_application"
            )
        self.stdout.write("")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "🔍 Dry run complete. Run without --dry-run to apply changes."
                )
            )
            return

        # Apply fixes
        self.stdout.write("Applying fixes...")
        updated_count = 0

        for m in mismatches:
            tt = m["tt_obj"]
            old_label = tt.ml_label
            tt.ml_label = "job_application"
            tt.save(update_fields=["ml_label"])
            updated_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✅ Updated {m['company']:35} | {old_label} → job_application"
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ Updated {updated_count} ThreadTracking records"))

        if missing_tt > 0:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  {missing_tt} messages have no ThreadTracking. "
                    "Run 'python manage.py sync_threadtracking' to create them."
                )
            )
