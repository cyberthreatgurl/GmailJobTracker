from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import Message, MessageLabel


class Command(BaseCommand):
    help = (
        "Remove the deprecated 'job_alert' label from the database.\n"
        "By default sets Message.ml_label to NULL for rows labeled 'job_alert'.\n"
        "Optionally, use --to-noise to map them to 'noise' instead. Also deletes any MessageLabel('job_alert')."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--to-noise",
            action="store_true",
            help="Map 'job_alert' messages to 'noise' instead of NULL",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without committing",
        )

    def handle(self, *args, **options):
        to_noise = options.get("to_noise")
        dry_run = options.get("dry_run")

        qs = Message.objects.filter(ml_label="job_alert")
        total = qs.count()
        if total == 0:
            self.stdout.write(
                self.style.SUCCESS("No messages with ml_label='job_alert' found.")
            )
        else:
            self.stdout.write(f"Found {total} messages with ml_label='job_alert'.")

        with transaction.atomic():
            # Use an explicit savepoint so we can roll back cleanly on dry-run without raising
            sid = transaction.savepoint()

            if total:
                if to_noise:
                    updated = qs.update(ml_label="noise")
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Updated {updated} messages: job_alert -> noise"
                        )
                    )
                else:
                    updated = qs.update(ml_label=None)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Cleared ml_label on {updated} messages (set to NULL)"
                        )
                    )

            # Remove MessageLabel row if present
            try:
                ml = MessageLabel.objects.get(label="job_alert")
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING("Would delete MessageLabel('job_alert')")
                    )
                else:
                    ml.delete()
                    self.stdout.write(
                        self.style.SUCCESS("Deleted MessageLabel('job_alert')")
                    )
            except MessageLabel.DoesNotExist:
                pass

            if dry_run:
                transaction.savepoint_rollback(sid)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; no changes were committed.")
                )
            else:
                transaction.savepoint_commit(sid)
                self.stdout.write(self.style.SUCCESS("Completed job_alert cleanup."))
