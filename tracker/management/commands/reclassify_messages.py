from django.core.management.base import BaseCommand
from tracker.models import Message
from ml_subject_classifier import predict_subject_type
from django.db.models import Count, Avg, Min, Max


class Command(BaseCommand):
    help = "Re-classify existing messages with updated ML model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-confidence",
            type=float,
            default=0.0,
            help="Only re-classify messages below this confidence (default: 0.0 = all)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of messages to process",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without saving",
        )

    def handle(self, *args, **options):
        min_conf = options["min_confidence"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        # Get messages to re-classify
        qs = Message.objects.all()
        if min_conf > 0:
            qs = qs.filter(confidence__lt=min_conf)

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}Re-classifying {total} messages..."
        )

        updated = 0
        changed = 0

        for i, msg in enumerate(qs.iterator(), 1):
            result = predict_subject_type(msg.subject, msg.body or "")

            old_label = msg.ml_label
            old_conf = msg.confidence

            new_label = result["label"]
            new_conf = result.get("confidence", 0.0)

            # Check if anything changed significantly
            label_changed = old_label != new_label
            conf_changed = abs(old_conf - new_conf) > 0.05

            if label_changed or conf_changed:
                changed += 1

                status = "📝" if label_changed else "🔄"
                self.stdout.write(f"  {status} [{i}/{total}] {msg.subject[:50]}")
                self.stdout.write(
                    f"      {old_label or 'None'}({old_conf:.2f}) → "
                    f"{new_label}({new_conf:.2f}) [{result.get('method', 'unknown')}]"
                )

                if not dry_run:
                    msg.ml_label = new_label
                    msg.confidence = new_conf
                    msg.save(update_fields=["ml_label", "confidence"])
                    updated += 1

            if i % 100 == 0:
                self.stdout.write(f"  Progress: {i}/{total}...")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"[DRY RUN] Would update {changed}/{total} messages")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Re-classified {changed}/{total} messages ({updated} saved)"
                )
            )

        # Check confidence distribution
        confidence_stats = (
            Message.objects.values("ml_label")
            .annotate(
                count=Count("id"),
                avg_conf=Avg("confidence"),
                min_conf=Min("confidence"),
                max_conf=Max("confidence"),
            )
            .order_by("-count")
        )

        self.stdout.write("\nConfidence distribution by label:")
        for stat in confidence_stats:
            self.stdout.write(
                f"  {stat['ml_label']}: {stat['count']} messages, "
                f"avg_conf={stat['avg_conf']:.2f}, "
                f"min_conf={stat['min_conf']:.2f}, "
                f"max_conf={stat['max_conf']:.2f}"
            )

        # Find messages with low confidence
        low_conf = Message.objects.filter(confidence__lt=0.6).count()
        self.stdout.write(f"\nMessages with confidence < 0.6: {low_conf}")

        # Check a specific low-confidence message
        msg = Message.objects.filter(confidence__lt=0.6).first()
        if msg:
            self.stdout.write(f"\nSubject: {msg.subject}")
            self.stdout.write(f"Current: {msg.ml_label} ({msg.confidence:.2f})")
            result = predict_subject_type(msg.subject, msg.body or "")
            self.stdout.write(
                f"New prediction: {result['label']} ({result['confidence']:.2f}) [{result['method']}]"
            )
