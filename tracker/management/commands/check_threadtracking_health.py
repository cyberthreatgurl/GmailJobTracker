"""Django management command to monitor ThreadTracking health.

Checks for:
- job_application/application Messages in the last N days that are missing a ThreadTracking row
- Mismatch between Message-based and ThreadTracking-based application company counts

Options:
- --days N (default: 7)
- --autofix (create missing ThreadTracking records)
- --exit-nonzero-on-issues (return exit code 1 if any issues found)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef, Q
from django.utils.timezone import now

from tracker.models import Message, ThreadTracking


class Command(BaseCommand):
    help = "Check ThreadTracking health for application messages and optionally autofix missing rows."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7, help="How many days back to check (default 7)")
        parser.add_argument(
            "--autofix",
            action="store_true",
            help="Create missing ThreadTracking rows for job_application/application messages",
        )
        parser.add_argument(
            "--exit-nonzero-on-issues",
            action="store_true",
            help="Exit with code 1 if issues are found",
        )

    def handle(self, *args, **options):
        days = int(options.get("days") or 7)
        autofix = bool(options.get("autofix"))
        exit_nonzero = bool(options.get("exit_nonzero_on_issues"))

        cutoff_dt = now() - self._td(days)
        cutoff_date = cutoff_dt.date()

        user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()
        headhunter_domains = self._load_headhunter_domains()

        # Build base Message queryset for job applications
        msg_qs = Message.objects.filter(
            ml_label__in=["job_application", "application"],
            timestamp__gte=cutoff_dt,
            company__isnull=False,
        ).exclude(company__status="headhunter")
        if user_email:
            msg_qs = msg_qs.exclude(sender__icontains=user_email)
        if headhunter_domains:
            msg_hh_sender_q = Q()
            for d in headhunter_domains:
                msg_hh_sender_q |= Q(sender__icontains=f"@{d}")
            msg_qs = msg_qs.exclude(msg_hh_sender_q)

        total_app_msgs = msg_qs.count()
        distinct_msg_companies = msg_qs.values("company_id").distinct().count()

        # Find messages missing ThreadTracking
        missing: List[Message] = []
        for m in msg_qs.only("thread_id", "company_id", "subject", "timestamp", "ml_label", "confidence"):
            if not ThreadTracking.objects.filter(thread_id=m.thread_id).exists():
                missing.append(m)

        # Build ThreadTracking-based distinct company count for comparison
        job_app_exists = Exists(
            Message.objects.filter(
                thread_id=OuterRef("thread_id"),
                ml_label__in=["job_application", "application"],
            )
        )
        tt_qs = (
            ThreadTracking.objects.filter(
                sent_date__isnull=False,
                company__isnull=False,
                sent_date__gte=cutoff_date,
            )
            .exclude(ml_label="noise")
            .exclude(company__status="headhunter")
            .annotate(has_job_app=job_app_exists)
            .filter(has_job_app=True)
        )
        distinct_tt_companies = tt_qs.values("company_id").distinct().count()

        # Report
        self.stdout.write("=" * 80)
        self.stdout.write("ThreadTracking Health Report")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Window: last {days} day(s) (from {cutoff_dt:%Y-%m-%d %H:%M} UTC)")
        self.stdout.write(f"Application messages: {total_app_msgs}")
        self.stdout.write(f"Distinct companies (Message-based): {distinct_msg_companies}")
        self.stdout.write(f"Distinct companies (ThreadTracking-based): {distinct_tt_companies}")
        self.stdout.write("")

        if missing:
            self.stdout.write(f"Missing ThreadTracking for {len(missing)} application message(s):")
            for m in missing[:50]:  # limit output
                self.stdout.write(
                    f"  - {m.company.name if m.company else 'Unknown'} | {m.timestamp.date()} | {m.subject[:70]}"
                )
            if len(missing) > 50:
                self.stdout.write(f"  ... and {len(missing) - 50} more ...")
        else:
            self.stdout.write("No missing ThreadTracking rows detected.")

        # Optional autofix
        created = 0
        if autofix and missing:
            created = self._autofix_create_tt(missing)
            self.stdout.write(f"Autofix: created {created} ThreadTracking record(s)")

        # Log file
        self._write_log(days, total_app_msgs, distinct_msg_companies, distinct_tt_companies, len(missing), created)

        # Exit code
        if exit_nonzero and (missing or distinct_msg_companies != distinct_tt_companies):
            raise SystemExit(1)

    # --- helpers ---
    @staticmethod
    def _td(days: int):
        from datetime import timedelta

        return timedelta(days=days)

    @staticmethod
    def _load_headhunter_domains() -> List[str]:
        try:
            p = Path("json/companies.json")
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                return [d.strip().lower() for d in data.get("headhunter_domains", []) if isinstance(d, str) and d]
        except Exception:
            pass
        return []

    @staticmethod
    def _autofix_create_tt(messages: List[Message]) -> int:
        created = 0
        for msg in messages:
            try:
                job_title = ""
                subject = msg.subject or ""
                if ":" in subject:
                    parts = subject.split(":", 1)
                    if len(parts) == 2:
                        job_title = parts[1].strip()[:255]
                if not job_title:
                    job_title = subject[:255] if subject else "Unknown"

                obj, was_created = ThreadTracking.objects.get_or_create(
                    thread_id=msg.thread_id,
                    defaults={
                        "company": msg.company,
                        "company_source": msg.company_source or "monitor",
                        "job_title": job_title,
                        "job_id": "",
                        "status": "application",
                        "sent_date": msg.timestamp.date(),
                        "rejection_date": None,
                        "interview_date": None,
                        "ml_label": msg.ml_label,
                        "ml_confidence": msg.confidence or 0.9,
                        "reviewed": msg.reviewed,
                    },
                )
                if was_created:
                    created += 1
            except Exception:
                # best-effort; continue
                continue
        return created

    @staticmethod
    def _write_log(days: int, total_msgs: int, msg_companies: int, tt_companies: int, missing: int, created: int):
        try:
            logs_dir = Path("logs")
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / "threadtracking_health.log"
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    (
                        f"[{now():%Y-%m-%d %H:%M:%S}] days={days} total_msgs={total_msgs} "
                        f"msg_companies={msg_companies} tt_companies={tt_companies} "
                        f"missing={missing} created={created}\n"
                    )
                )
        except Exception:
            # Logging failures shouldn't break the command
            pass
