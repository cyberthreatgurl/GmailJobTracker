import os, sys, json
from datetime import datetime

ROOT = os.path.abspath(r"c:\Users\kaver\code\GmailJobTracker")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import ThreadTracking, Message
from django.db import transaction

import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--apply", action="store_true", help="Apply changes (default dry-run)"
)
parser.add_argument(
    "--threshold",
    type=float,
    default=0.7,
    help="ML confidence threshold to keep interview_date",
)
args = parser.parse_args()

DRY_RUN = not args.apply
THRESHOLD = args.threshold

# Keep criteria:
# - ThreadTracking.interview_completed == True (do not clear)
# - OR ml_label in ('interview_invite','interview') AND ml_confidence >= THRESHOLD
# - OR there exists a Message in the thread with ml_label in ('interview_invite','interview')

candidates = []
for tt in ThreadTracking.objects.filter(interview_date__isnull=False).select_related(
    "company"
):
    keep = False
    if tt.interview_completed:
        keep = True
    ml_label = (tt.ml_label or "").strip()
    ml_conf = float(tt.ml_confidence) if tt.ml_confidence is not None else 0.0
    if ml_label in ("interview_invite", "interview") and ml_conf >= THRESHOLD:
        keep = True
    # message-level check
    has_msg_interview = Message.objects.filter(
        thread_id=tt.thread_id, ml_label__in=["interview_invite", "interview"]
    ).exists()
    if has_msg_interview:
        keep = True
    if not keep:
        candidates.append(
            {
                "id": tt.id,
                "thread_id": tt.thread_id,
                "company": tt.company.name if tt.company else None,
                "ml_label": ml_label,
                "ml_confidence": ml_conf,
                "interview_date": str(tt.interview_date),
            }
        )

now_ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
backup_path = os.path.join(ROOT, "scripts", f"cleanup_strict_backup_{now_ts}.json")
with open(backup_path, "w", encoding="utf-8") as f:
    json.dump(candidates, f, indent=2)

print(
    f"Found {len(candidates)} ThreadTracking rows that would be cleared (backup written to {backup_path})"
)
if DRY_RUN:
    print("Dry run. Re-run with --apply to clear these interview_date values.")
    sys.exit(0)

# Apply changes
changed = 0
with transaction.atomic():
    for c in candidates:
        tt = ThreadTracking.objects.filter(id=c["id"]).first()
        if tt and tt.interview_date is not None:
            tt.interview_date = None
            tt.save()
            changed += 1
print(f"Cleared interview_date on {changed} ThreadTracking rows")
