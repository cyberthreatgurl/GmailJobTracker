import json
from email.utils import parseaddr
from pathlib import Path

from django.core.management.base import BaseCommand

from tracker.models import Message, ThreadTracking


class Command(BaseCommand):
    help = "Mark messages from job board domains (from json/companies.json) as noise."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="If set, apply changes. Otherwise runs as dry-run.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options.get("apply"))
        p = Path("json/companies.json")
        if not p.exists():
            self.stdout.write(self.style.ERROR("json/companies.json not found"))
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        job_board_domains = [d.lower() for d in data.get("job_board_domains", []) if isinstance(d, str) and d]
        if not job_board_domains:
            self.stdout.write(self.style.WARNING("No job_board_domains configured in companies.json"))
            return

        self.stdout.write(f"Found {len(job_board_domains)} job board domains to check")

        # Candidate messages: those not already labeled 'noise'
        qs = Message.objects.exclude(ml_label="noise").only("id", "sender", "thread_id", "ml_label")
        to_change = []
        for m in qs:
            addr = parseaddr(m.sender or "")[1] or ""
            dom = addr.split("@")[-1].lower() if "@" in addr else ""
            if not dom:
                continue
            for jb in job_board_domains:
                if dom == jb or dom.endswith("." + jb):
                    to_change.append((m, dom))
                    break

        self.stdout.write(f"Candidates found: {len(to_change)} messages")
        if not to_change:
            return

        if not apply_changes:
            # Dry-run: list a few examples
            for m, dom in to_change[:20]:
                self.stdout.write(f"Would mark Message id={m.id} sender={m.sender} domain={dom} (current label={m.ml_label})")
            self.stdout.write(self.style.WARNING("Dry-run: no changes applied. Re-run with --apply to modify database."))
            return

        updated_msgs = 0
        updated_apps = 0
        from tracker.label_helpers import label_message_and_propagate

        for m, dom in to_change:
            try:
                # Use central helper to save and propagate label change
                label_message_and_propagate(m, "noise", confidence=0.99)
                updated_msgs += 1
                # propagate helper will update existing ThreadTracking; count if present
                if m.thread_id:
                    tt = ThreadTracking.objects.filter(thread_id=m.thread_id).first()
                    if tt and tt.ml_label == "noise":
                        updated_apps += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to update Message id={m.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Updated {updated_msgs} Message(s) and {updated_apps} ThreadTracking(s)"))
