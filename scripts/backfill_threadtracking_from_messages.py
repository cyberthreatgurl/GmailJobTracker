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
    created = 0
    updated = 0
    # Find messages manually labeled as applications/interviews
    qs = Message.objects.filter(
        ml_label__in=["job_application", "interview_invite"]
    ).order_by("-timestamp")
    for msg in qs:
        if not msg.thread_id:
            continue
        tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if tt:
            # Ensure thread ml_label aligns
            if tt.ml_label != msg.ml_label:
                tt.ml_label = msg.ml_label
                tt.ml_confidence = msg.confidence or tt.ml_confidence
                tt.save()
                updated += 1
            continue
        # No ThreadTracking exists; only create if company available
        if not msg.company:
            continue
        try:
            ThreadTracking.objects.create(
                thread_id=msg.thread_id,
                company=msg.company,
                company_source=msg.company_source or "manual_backfill",
                job_title="",
                job_id="",
                status="application",
                sent_date=(msg.timestamp.date() if msg.timestamp else None),
                ml_label=msg.ml_label,
                ml_confidence=(msg.confidence or 0.0),
            )
            created += 1
        except Exception as e:
            print("Failed to create for", msg.id, "error:", e)

    print(f"Backfill complete. Created={created}, Updated={updated}")


if __name__ == "__main__":
    main()
