import csv
from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Count

from tracker.models import Message


class Command(BaseCommand):
    help = (
        "Audit message labeling accuracy and export/import ground truth by msg_id.\n\n"
        "Use --export-reviewed to export reviewed messages as CSV.\n"
        "Use --compare <csv> to compare current labels to a CSV ground truth keyed by msg_id."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--export-reviewed",
            metavar="CSV_PATH",
            help="Export reviewed=True messages to CSV",
        )
        parser.add_argument(
            "--compare",
            metavar="CSV_PATH",
            help="Compare current labels against ground truth CSV (columns: msg_id,label)",
        )
        parser.add_argument("--limit", type=int, help="Limit the number of messages processed for speed")
        parser.add_argument(
            "--days",
            type=int,
            help="Restrict to messages from last N days for export/compare",
        )

    def handle(self, *args, **options):
        export_path = options.get("export_reviewed")
        compare_path = options.get("compare")
        limit = options.get("limit")
        days = options.get("days")

        if export_path:
            self._export_reviewed(export_path, limit=limit, days=days)

        if compare_path:
            self._compare_against_csv(compare_path, limit=limit, days=days)

        if not export_path and not compare_path:
            # Default: print simple label distribution stats
            self._print_label_stats(limit=limit, days=days)

    def _export_reviewed(self, path: str, limit=None, days=None):
        qs = Message.objects.filter(reviewed=True)
        if days:
            from django.utils import timezone

            since = timezone.now() - timezone.timedelta(days=days)
            qs = qs.filter(timestamp__gte=since)
        qs = qs.order_by("-timestamp")
        if limit:
            qs = qs[:limit]
        rows = qs.values("msg_id", "ml_label", "subject", "sender", "timestamp")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["msg_id", "label", "subject", "sender", "timestamp"])
            for r in rows:
                w.writerow(
                    [
                        r["msg_id"],
                        r["ml_label"],
                        r["subject"],
                        r["sender"],
                        r["timestamp"],
                    ]
                )
        self.stdout.write(self.style.SUCCESS(f"Exported {qs.count()} reviewed messages to {path}"))

    def _compare_against_csv(self, path: str, limit=None, days=None):
        # Load ground truth from CSV: expecting columns msg_id,label
        gt = {}
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                mid = row.get("msg_id")
                lab = row.get("label")
                if mid and lab:
                    gt[mid] = lab
        if not gt:
            self.stdout.write(self.style.WARNING("No ground truth loaded from CSV (msg_id,label)"))
            return

        qs = Message.objects.filter(msg_id__in=list(gt.keys()))
        if days:
            from django.utils import timezone

            since = timezone.now() - timezone.timedelta(days=days)
            qs = qs.filter(timestamp__gte=since)
        qs = qs.order_by("-timestamp")
        if limit:
            qs = qs[:limit]

        total = 0
        correct = 0
        per_label_total = Counter()
        per_label_correct = Counter()
        confusion = Counter()  # (gt, pred) -> count

        for m in qs.iterator():
            total += 1
            gt_label = gt.get(m.msg_id)
            pred = m.ml_label or "unknown"
            per_label_total[gt_label] += 1
            if pred == gt_label:
                correct += 1
                per_label_correct[gt_label] += 1
            confusion[(gt_label, pred)] += 1

        acc = (correct / total) if total else 0.0
        self.stdout.write(self.style.NOTICE(f"Compared {total} messages; accuracy={acc:.3f}"))
        self.stdout.write("Per-label accuracy:")
        for lab, n in per_label_total.most_common():
            a = (per_label_correct[lab] / n) if n else 0.0
            self.stdout.write(f"  {lab:18s} {a:.3f}  ({per_label_correct[lab]}/{n})")

        self.stdout.write("\nTop confusion pairs:")
        for (gt_lab, pred_lab), n in confusion.most_common(20):
            if gt_lab != pred_lab:
                self.stdout.write(f"  {gt_lab:18s} -> {pred_lab:18s} : {n}")

    def _print_label_stats(self, limit=None, days=None):
        qs = Message.objects.all()
        if days:
            from django.utils import timezone

            since = timezone.now() - timezone.timedelta(days=days)
            qs = qs.filter(timestamp__gte=since)
        if limit:
            qs = qs[:limit]
        dist = qs.values("ml_label").annotate(n=Count("id")).order_by("-n")
        self.stdout.write("Current label distribution:")
        for row in dist:
            self.stdout.write(f"  {row['ml_label'] or 'unknown':18s} : {row['n']}")
