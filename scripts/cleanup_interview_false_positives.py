import os
import sys
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import ThreadTracking, Message
from django.db import transaction

import argparse

THRESHOLD = float(os.environ.get("INTERVIEW_CONF_THRESHOLD", 0.6))

parser = argparse.ArgumentParser(
    description="Cleanup low-confidence interview_date ThreadTracking rows"
)
parser.add_argument(
    "--apply", action="store_true", help="Apply changes (default is dry-run)"
)
parser.add_argument(
    "--threshold",
    type=float,
    help="Confidence threshold override (default from env or 0.6)",
)
args = parser.parse_args()

if args.threshold is not None:
    THRESHOLD = args.threshold

DRY_RUN = not args.apply


def summarize_tt(tt):
    return {
        "id": tt.id,
        "thread_id": tt.thread_id,
        "company_id": tt.company_id,
        "company_name": tt.company.name if tt.company else None,
        "sent_date": str(tt.sent_date) if tt.sent_date else None,
        "interview_date": str(tt.interview_date) if tt.interview_date else None,
        "interview_completed": tt.interview_completed,
        "ml_label": tt.ml_label,
        "ml_confidence": tt.ml_confidence,
        "status": tt.status,
        "company_source": tt.company_source,
    }


def main():
    # Candidates: non-completed interview_date entries
    candidates = ThreadTracking.objects.filter(
        interview_date__isnull=False, interview_completed=False
    )
    to_clear = []

    for tt in candidates:
        # If there are message-level interview labels, keep
        msgs = Message.objects.filter(thread_id=tt.thread_id)
        has_msg_interview = msgs.filter(
            ml_label__in=["interview_invite", "interview"]
        ).exists()
        ml_conf = float(tt.ml_confidence) if tt.ml_confidence is not None else 0.0
        # Mark for clearing when no message-level interview and low thread ML confidence
        if (not has_msg_interview) and (ml_conf < THRESHOLD):
            to_clear.append({"tt": tt, "msgs": list(msgs[:20]), "ml_conf": ml_conf})

    now_ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join("scripts", f"interview_date_backup_{now_ts}.json")

    # Save backup
    dump = []
    for item in to_clear:
        tt = item["tt"]
        msgs = item["msgs"]
        dump.append(
            {
                "threadtracking": summarize_tt(tt),
                "messages": [
                    {
                        "id": m.id,
                        "msg_id": m.msg_id,
                        "thread_id": m.thread_id,
                        "timestamp": str(m.timestamp),
                        "ml_label": m.ml_label,
                        "subject": (m.subject or "")[:300],
                    }
                    for m in msgs
                ],
            }
        )

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2)

    print(f"Backup of {len(dump)} ThreadTracking rows written to {backup_path}")

    if DRY_RUN:
        print("Dry run mode - no changes made. Set DRY_RUN=false to apply changes.")
        return

    # Apply changes
    changed = 0
    with transaction.atomic():
        for item in to_clear:
            tt = item["tt"]
            tt.interview_date = None
            tt.save()
            changed += 1

    print(f"Cleared interview_date on {changed} ThreadTracking rows.")


if __name__ == "__main__":
    print(
        f"Running cleanup_interview_false_positives.py (threshold={THRESHOLD}, dry_run={DRY_RUN})"
    )
    main()
