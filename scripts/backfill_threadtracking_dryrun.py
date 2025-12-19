"""Dry-run backfill: report how many ThreadTracking rows would be created/updated without writing changes."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message, ThreadTracking


def main():
    would_create = 0
    would_update = 0
    examples_create = []
    examples_update = []

    qs = Message.objects.filter(
        ml_label__in=["job_application", "interview_invite"]
    ).order_by("-timestamp")
    for msg in qs:
        if not msg.thread_id:
            continue
        tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if tt:
            if tt.ml_label != msg.ml_label:
                would_update += 1
                if len(examples_update) < 10:
                    examples_update.append(
                        {
                            "msg_id": msg.id,
                            "thread_id": msg.thread_id,
                            "msg_label": msg.ml_label,
                            "tt_label": tt.ml_label,
                        }
                    )
            continue
        if not msg.company:
            continue
        would_create += 1
        if len(examples_create) < 10:
            examples_create.append(
                {
                    "msg_id": msg.id,
                    "thread_id": msg.thread_id,
                    "label": msg.ml_label,
                    "company": msg.company.name if msg.company else None,
                }
            )

    print(f"Dry-run backfill: would create={would_create}, would update={would_update}")
    if examples_create:
        print("Examples (create):")
        for e in examples_create:
            print("  ", e)
    if examples_update:
        print("Examples (update):")
        for e in examples_update:
            print("  ", e)


if __name__ == "__main__":
    main()
