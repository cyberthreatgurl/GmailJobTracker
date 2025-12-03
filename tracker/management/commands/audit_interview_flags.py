import json
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import ThreadTracking, Message
from pathlib import Path


class Command(BaseCommand):
    help = (
        "Audit ThreadTracking rows that have `interview_date` set but look like false-positives."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.7,
            help="ML confidence threshold to consider an ml_label reliable (default: 0.7)",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help=(
                "Path to write JSON report. Defaults to `scripts/audit_interview_report_<ts>.json`"
            ),
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="If set, clear `interview_date` on flagged rows after writing backup",
        )
        parser.add_argument(
            "--preserve",
            type=str,
            default="",
            help=(
                "Comma-separated ThreadTracking IDs to preserve (not cleared). Example: --preserve=809,922"
            ),
        )

    def handle(self, *args, **options):
        threshold = float(options.get("threshold") or 0.7)
        out = options.get("output")
        apply_changes = options.get("apply")
        preserve_raw = options.get("preserve") or ""
        preserve_ids = set()
        if preserve_raw:
            for part in preserve_raw.split(","):
                part = part.strip()
                if part:
                    try:
                        preserve_ids.add(int(part))
                    except ValueError:
                        self.stdout.write(self.style.WARNING(f"Ignored invalid preserve id: {part}"))

        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        if not out:
            out = f"scripts/audit_interview_report_{ts}.json"
        backup_path = f"scripts/audit_interview_backup_{ts}.json"

        self.stdout.write(f"Scanning ThreadTracking rows with interview_date set (threshold={threshold})...")

        # Load known companies from json to avoid flagging legitimate companies
        known_companies = set()
        try:
            p = Path("json/companies.json")
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                for name in data.get("known", []):
                    if isinstance(name, str) and name.strip():
                        known_companies.add(name.strip())
        except Exception:
            pass

        candidates = []
        q = ThreadTracking.objects.filter(interview_date__isnull=False)
        total = q.count()
        self.stdout.write(f"Total ThreadTracking with interview_date: {total}")

        for tt in q.order_by("id"):
            # Keep rules: interview_completed True, any message in thread labeled interview/interview_invite,
            # or ml_label for thread is interview_invite/interview with confidence >= threshold
            keep = False
            reason = []
            # If the ThreadTracking references a known company from our list, treat it as legitimate
            if tt.company and tt.company.name in known_companies:
                keep = True
                reason.append("known_company")
            if tt.interview_completed:
                keep = True
                reason.append("completed")

            # messages in thread with interview labels
            messages = list(Message.objects.filter(thread_id=tt.thread_id).order_by("timestamp"))
            msg_labels = [m.ml_label for m in messages if getattr(m, "ml_label", None)]
            if any(l in ("interview_invite", "interview") for l in msg_labels):
                keep = True
                reason.append("message_labeled")

            if tt.ml_label in ("interview_invite", "interview") and (tt.ml_confidence or 0) >= threshold:
                keep = True
                reason.append(f"ml_confident({tt.ml_confidence:.2f})")

            flagged = not keep

            item = {
                "id": tt.id,
                "thread_id": tt.thread_id,
                "company_id": tt.company.id if tt.company_id else None,
                "company_name": getattr(tt.company, "name", None),
                "sent_date": tt.sent_date.isoformat() if tt.sent_date else None,
                "interview_date": tt.interview_date.isoformat() if tt.interview_date else None,
                "ml_label": tt.ml_label,
                "ml_confidence": float(tt.ml_confidence or 0),
                "status": tt.status,
                "messages_count": len(messages),
                "message_labels": msg_labels,
                "keep_reasons": reason,
                "flagged": flagged,
            }
            if flagged:
                # Candidate to consider clearing
                candidates.append(item)

        report = {
            "timestamp": ts,
            "threshold": threshold,
            "total_with_interview_date": total,
            "flagged_count": len(candidates),
            "flagged": candidates,
        }

        # ensure scripts dir exists
        try:
            import os

            os.makedirs("scripts", exist_ok=True)
        except Exception:
            pass

        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)

        self.stdout.write(self.style.SUCCESS(f"Wrote audit report to: {out}"))

        if not candidates:
            self.stdout.write(self.style.SUCCESS("No flagged rows found. Nothing to apply."))
            return

        # Always write a backup of all interview_date rows before any apply
        full_rows = []
        for tt in q.order_by("id"):
            full_rows.append({
                "id": tt.id,
                "thread_id": tt.thread_id,
                "company_id": tt.company.id if tt.company_id else None,
                "company_name": getattr(tt.company, "name", None),
                "sent_date": tt.sent_date.isoformat() if tt.sent_date else None,
                "interview_date": tt.interview_date.isoformat() if tt.interview_date else None,
                "ml_label": tt.ml_label,
                "ml_confidence": float(tt.ml_confidence or 0),
            })
        with open(backup_path, "w", encoding="utf-8") as fh:
            json.dump({"backup_ts": ts, "rows": full_rows}, fh, indent=2, default=str)

        self.stdout.write(self.style.SUCCESS(f"Wrote full backup to: {backup_path}"))

        if apply_changes:
            cleared_ids = []
            for item in candidates:
                if item["id"] in preserve_ids:
                    self.stdout.write(self.style.WARNING(f"Preserving id {item['id']} per --preserve"))
                    continue
                tt = ThreadTracking.objects.get(id=item["id"])
                tt.interview_date = None
                tt.save()
                cleared_ids.append(item["id"])

            self.stdout.write(self.style.SUCCESS(f"Cleared interview_date on {len(cleared_ids)} rows."))
            apply_report = f"scripts/audit_interview_apply_{ts}.json"
            with open(apply_report, "w", encoding="utf-8") as fh:
                json.dump({"cleared_ids": cleared_ids, "preserved": list(preserve_ids)}, fh, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Wrote apply report to: {apply_report}"))
        else:
            self.stdout.write(self.style.WARNING("Dry-run: no changes applied. Use --apply to clear flagged rows."))
