"""Import NDJSON audit lines from `logs/clear_reviewed_audit.log` into `AuditEvent` rows.

Usage:
  python manage.py import_audit_logs --file logs/clear_reviewed_audit.log [--apply] [--limit N]

By default the command runs as a dry-run and prints what it would import. Pass
`--apply` to persist entries into the DB. When applying, a timestamped backup
of the source file is created automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import AuditEvent


def _parse_iso(dt_str: Optional[str]):
    if not dt_str:
        return None
    try:
        # Try ISO parser; Django can accept naive datetimes here and auto_now_add will
        # be used if created_at isn't provided.
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


class Command(BaseCommand):
    help = "Import NDJSON audit lines into AuditEvent (dry-run by default)."

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--file",
            dest="file",
            default="logs/clear_reviewed_audit.log",
            help="Path to NDJSON audit file",
        )
        parser.add_argument(
            "--apply",
            dest="apply",
            action="store_true",
            help="Actually persist imports to DB",
        )
        parser.add_argument(
            "--limit",
            dest="limit",
            type=int,
            default=0,
            help="Limit number of lines processed (0 == all)",
        )
        parser.add_argument(
            "--skip-existing",
            dest="skip_existing",
            action="store_true",
            help="Skip entries that appear to already exist",
        )

    def handle(self, *args, **options):
        path = options["file"]
        apply_changes = bool(options["apply"])
        limit = int(options.get("limit") or 0)
        skip_existing = bool(options.get("skip_existing"))

        if not os.path.exists(path):
            self.stderr.write(f"Audit log file not found: {path}")
            return

        self.stdout.write(f"Reading audit file: {path}")

        to_create = []
        seen = 0

        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                seen += 1
                try:
                    obj = json.loads(line)
                except Exception as e:
                    self.stderr.write(f"Skipping malformed JSON line {seen}: {e}")
                    continue

                # Map known fields
                created_at = _parse_iso(
                    obj.get("created_at") or obj.get("timestamp") or obj.get("ts")
                )
                user = obj.get("user") or obj.get("username") or obj.get("actor")
                action = obj.get("action") or obj.get("type") or "clear_reviewed"
                source = obj.get("source") or obj.get("origin")
                msg_id = obj.get("msg_id") or obj.get("message_id")
                db_id = obj.get("db_id") or obj.get("id")
                thread_id = obj.get("thread_id")
                company_id = obj.get("company_id")
                details = obj.get("details")
                error = obj.get("error")
                trace = obj.get("trace")
                pid = obj.get("pid")

                # Normalize details to JSON text
                details_text = None
                if details is not None:
                    try:
                        details_text = json.dumps(details, ensure_ascii=False)
                    except Exception:
                        details_text = str(details)

                # Build a candidate dict
                cand = dict(
                    created_at=created_at,
                    user=user,
                    action=action,
                    source=source,
                    msg_id=msg_id,
                    db_id=db_id,
                    thread_id=thread_id,
                    company_id=company_id,
                    details=details_text,
                    error=error,
                    trace=trace,
                    pid=pid,
                )

                to_create.append(cand)

                if limit and len(to_create) >= limit:
                    break

        self.stdout.write(f"Parsed {len(to_create)} audit entries (from {seen} lines).")

        if not to_create:
            return

        if not apply_changes:
            # Dry run: list a summary and exit
            self.stdout.write("Dry-run mode (no DB writes). Use --apply to persist.")
            for i, cand in enumerate(to_create[:50], start=1):
                self.stdout.write(
                    f"{i}: action={cand['action']} user={cand.get('user')} msg_id={cand.get('msg_id')} db_id={cand.get('db_id')}"
                )
            if len(to_create) > 50:
                self.stdout.write(f"... and {len(to_create)-50} more entries (trimmed)")
            return

        # When applying, back up the file first
        backup_path = f"{path}.bak.{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        try:
            shutil.copy2(path, backup_path)
            self.stdout.write(f"Created backup: {backup_path}")
        except Exception as e:
            self.stderr.write(f"Warning: failed to create backup {backup_path}: {e}")

        created = 0
        skipped = 0
        errors = 0

        with transaction.atomic():
            for cand in to_create:
                try:
                    # Basic dedupe heuristics
                    existing_q = None
                    if cand.get("pid") is not None:
                        existing_q = AuditEvent.objects.filter(pid=cand["pid"])
                    elif (
                        cand.get("created_at") is not None
                        and cand.get("action")
                        and cand.get("msg_id")
                    ):
                        existing_q = AuditEvent.objects.filter(
                            created_at=cand["created_at"],
                            action=cand["action"],
                            msg_id=cand["msg_id"],
                        )

                    if existing_q is not None and existing_q.exists():
                        skipped += 1
                        if not skip_existing:
                            self.stdout.write(
                                f"Skipping existing (dedupe) action={cand['action']} msg_id={cand.get('msg_id')} pid={cand.get('pid')}"
                            )
                        continue

                    ae = AuditEvent(
                        user=cand.get("user"),
                        action=cand.get("action") or "clear_reviewed",
                        source=cand.get("source"),
                        msg_id=cand.get("msg_id"),
                        db_id=cand.get("db_id"),
                        thread_id=cand.get("thread_id"),
                        company_id=cand.get("company_id"),
                        details=cand.get("details"),
                        error=cand.get("error"),
                        trace=cand.get("trace"),
                        pid=cand.get("pid"),
                    )

                    if cand.get("created_at"):
                        # created_at is auto_now_add; set directly if parsed
                        ae.created_at = cand["created_at"]

                    ae.save()
                    created += 1
                except Exception as e:
                    errors += 1
                    self.stderr.write(
                        f"Failed to create AuditEvent for {cand.get('msg_id') or cand.get('db_id')}: {e}"
                    )

        self.stdout.write(
            f"Import complete: created={created} skipped={skipped} errors={errors}"
        )
