from django.core.management.base import BaseCommand
import csv

from ml_subject_classifier import predict_subject_type
from tracker.models import Message


class Command(BaseCommand):
    help = "Export a DB-backed dry-run reclassification CSV with message ids"

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-confidence",
            type=float,
            default=0.0,
            help="Only include messages below this confidence",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of messages to process",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="reclassify_dryrun_full.csv",
            help="Output CSV path (relative to repo root)",
        )
        parser.add_argument(
            "--include-reviewed",
            action="store_true",
            help="Include messages marked reviewed (default: excluded)",
        )

    def handle(self, *args, **options):
        min_conf = options["min_confidence"]
        limit = options["limit"]
        out_path = options["output"]
        include_reviewed = bool(options.get("include_reviewed", False))

        qs = Message.objects.all().order_by("id")
        if min_conf > 0:
            qs = qs.filter(confidence__lt=min_conf)

        if not include_reviewed:
            qs = qs.exclude(reviewed=True)

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"[DRY RUN] Exporting predictions for {total} messages to {out_path}...")

        with open(out_path, "w", encoding="utf-8", newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                "message_id",
                "thread_id",
                "reviewed",
                "subject",
                "old_label",
                "old_conf",
                "new_label",
                "new_conf",
                "method",
            ])

            for i, msg in enumerate(qs.iterator(), 1):
                result = predict_subject_type(msg.subject, msg.body or "", sender=msg.sender)
                new_label = result.get("label")
                new_conf = result.get("confidence", 0.0)
                method = result.get("method", "unknown")

                writer.writerow([
                    msg.id,
                    msg.thread_id if hasattr(msg, "thread_id") else getattr(msg, "thread", None) and msg.thread.id,
                    bool(msg.reviewed),
                    msg.subject,
                    msg.ml_label or "",
                    f"{(msg.confidence or 0.0):.2f}",
                    new_label,
                    f"{new_conf:.2f}",
                    method,
                ])

                if i % 200 == 0:
                    self.stdout.write(f"  Progress: {i}/{total}...")

        self.stdout.write(self.style.SUCCESS(f"Wrote CSV: {out_path} ({total} rows)"))
