"""
Management command to update all company statuses based on latest message.

This ensures Company.status reflects:
- rejection: Latest message is a rejection
- interview: Latest message is an interview invite
- application: Latest message is job_application (< GHOSTED_DAYS_THRESHOLD)
- ghosted: Latest message is job_application (>= GHOSTED_DAYS_THRESHOLD)
- headhunter: Latest message is head_hunter

Usage:
    python manage.py update_company_statuses [--dry-run]
"""

import os
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from tracker.models import Company, Message


class Command(BaseCommand):
    help = "Update all company statuses based on latest message and GHOSTED_DAYS_THRESHOLD"

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

        # Get GHOSTED_DAYS_THRESHOLD from environment or database
        ghosted_days_threshold = 30
        try:
            from tracker.models import AppSetting
            db_val = (
                AppSetting.objects.filter(key="GHOSTED_DAYS_THRESHOLD")
                .values_list("value", flat=True)
                .first()
            )
            if db_val and str(db_val).strip():
                ghosted_days_threshold = int(str(db_val).strip())
        except Exception:
            pass

        try:
            env_val = (os.environ.get("GHOSTED_DAYS_THRESHOLD") or "").strip()
            if env_val:
                ghosted_days_threshold = int(env_val)
        except ValueError:
            pass

        if ghosted_days_threshold < 1 or ghosted_days_threshold > 3650:
            ghosted_days_threshold = 30

        self.stdout.write(f"Using GHOSTED_DAYS_THRESHOLD: {ghosted_days_threshold} days")
        self.stdout.write("")

        # Get all companies
        companies = Company.objects.all()
        updated_count = 0
        no_messages_count = 0
        no_change_count = 0

        for company in companies:
            # Get latest message with ml_label
            latest_msg = (
                Message.objects.filter(company=company, ml_label__isnull=False)
                .order_by("-timestamp")
                .first()
            )

            if not latest_msg:
                no_messages_count += 1
                continue

            # Skip companies with status="new" - preserve manual "new" status
            if company.status == "new":
                no_change_count += 1
                continue

            latest_label = latest_msg.ml_label
            old_status = company.status
            new_status = None

            # Calculate new status
            if latest_label == "rejection":
                new_status = "rejected"
            elif latest_label == "head_hunter":
                new_status = "headhunter"
            elif latest_label == "interview_invite":
                new_status = "interview"
            elif latest_label == "job_application":
                # Check if it's past ghosted threshold
                if latest_msg.timestamp:
                    days_since = (now() - latest_msg.timestamp).days
                    if days_since >= ghosted_days_threshold:
                        new_status = "ghosted"
                    else:
                        new_status = "application"
                else:
                    new_status = "application"
            # For other labels (other, referral, noise), don't change status

            # Update if changed
            if new_status and old_status != new_status:
                self.stdout.write(
                    f"  {company.name:40} | {old_status or '(none)':15} → {new_status:15} | Latest: {latest_label}"
                )
                if not dry_run:
                    company.status = new_status
                    company.save(update_fields=["status"])
                updated_count += 1
            else:
                no_change_count += 1

        # Report summary
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Companies processed: {companies.count()}")
        self.stdout.write(f"Status updated: {updated_count}")
        self.stdout.write(f"No change needed: {no_change_count}")
        self.stdout.write(f"No messages: {no_messages_count}")
        self.stdout.write("=" * 60)

        if dry_run and updated_count > 0:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "🔍 Dry run complete. Run without --dry-run to apply changes."
                )
            )
        elif updated_count > 0:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"✅ Updated {updated_count} company statuses"))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("✅ All company statuses are already correct!"))
