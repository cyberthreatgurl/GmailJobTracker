import os
import json
from datetime import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Clear the reviewed flag for Message rows. Writes an audit entry to logs/clear_reviewed_audit.log"

    def add_arguments(self, parser):
        parser.add_argument(
            "--msg-ids",
            nargs="+",
            help="One or more Message.msg_id values to unmark (space separated)",
        )
        parser.add_argument(
            "--db-ids",
            nargs="+",
            help="One or more Message DB primary keys to unmark (space separated)",
        )
        parser.add_argument(
            "--clear-apps",
            action="store_true",
            help="Also clear ThreadTracking.reviewed for affected threads",
        )

    def handle(self, *args, **opts):
        from tracker.models import Message, ThreadTracking

        msg_ids = opts.get("msg_ids") or []
        db_ids = opts.get("db_ids") or []
        clear_apps = opts.get("clear_apps")

        if not msg_ids and not db_ids:
            self.stderr.write("Provide --msg-ids or --db-ids to operate on")
            return

        qs = Message.objects.none()
        if msg_ids:
            qs = qs.union(Message.objects.filter(msg_id__in=msg_ids))
        if db_ids:
            try:
                int_ids = [int(x) for x in db_ids]
                qs = qs.union(Message.objects.filter(pk__in=int_ids))
            except ValueError:
                self.stderr.write("--db-ids must be integers")
                return

        matched = qs.count()
        if matched == 0:
            self.stdout.write("No messages matched the provided ids")
            return

        updated = qs.update(reviewed=False)

        # Optionally clear ThreadTracking.reviewed for affected threads
        apps_updated = 0
        if clear_apps:
            thread_ids = qs.exclude(thread_id__isnull=True).values_list("thread_id", flat=True)
            if thread_ids:
                apps_updated = ThreadTracking.objects.filter(thread_id__in=list(thread_ids)).update(reviewed=False)

        # Write audit log
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        audit_path = os.path.join(log_dir, "clear_reviewed_audit.log")
        # Collect detailed context about affected messages
        details = []
        try:
            for m in qs[:1000]:
                details.append(
                    {
                        "msg_id": m.msg_id,
                        "db_id": m.pk,
                        "thread_id": m.thread_id,
                        "company_id": m.company.id if getattr(m, "company", None) else None,
                    }
                )
        except Exception:
            # If iteration fails, fall back to minimal lists
            details = None

        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
            "msg_ids": list(msg_ids),
            "db_ids": list(db_ids),
            "matched": matched,
            "updated": updated,
            "apps_updated": apps_updated,
            "details": details,
            "pid": os.getpid(),
        }
        try:
            with open(audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Also persist to DB for easier querying
            try:
                from tracker.models import AuditEvent

                AuditEvent.objects.create(
                    user=entry.get("user"),
                    action="clear_reviewed",
                    source="management_command",
                    details=json.dumps(entry, ensure_ascii=False),
                    pid=entry.get("pid"),
                )
            except Exception:
                # Do not fail the command if DB write fails; log to stderr
                try:
                    import traceback

                    with open(audit_path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"ts": datetime.utcnow().isoformat(), "error": "DB write failed", "trace": traceback.format_exc()}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception as e:
            # Attempt to write fallback audit with trace
            try:
                import traceback

                fallback = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
                    "error": str(e),
                    "trace": traceback.format_exc(),
                    "pid": os.getpid(),
                }
                with open(audit_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(fallback, ensure_ascii=False) + "\n")
            except Exception:
                self.stderr.write(f"Failed to write audit log: {e}")

        self.stdout.write(f"Cleared reviewed for {updated} messages (matched={matched}). apps_updated={apps_updated}")
