import os, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message, ThreadTracking

THREAD_ID = "1993967845d27fd2"

msg = Message.objects.filter(thread_id=THREAD_ID).order_by("timestamp").first()
if not msg:
    print(f"No Message found for thread_id={THREAD_ID}")
    sys.exit(1)

print(
    f"Found message: id={msg.id} msg_id={msg.msg_id} label={msg.ml_label} company={msg.company}"
)

tt, created = ThreadTracking.objects.get_or_create(
    thread_id=msg.thread_id,
    defaults={
        "company": msg.company,
        "company_source": msg.company_source or "reingest_manual",
        "job_title": "",
        "job_id": "",
        "status": msg.ml_label or "interview",
        "sent_date": msg.timestamp.date(),
        "rejection_date": None,
        "interview_date": None,
        "ml_label": msg.ml_label,
        "ml_confidence": msg.confidence if hasattr(msg, "confidence") else None,
        "reviewed": False,
    },
)

if created:
    print(f"Created ThreadTracking id={tt.id} for thread {THREAD_ID}")
else:
    print(f"ThreadTracking already exists id={tt.id}; updating fields if needed")
    updated = False
    if tt.company != msg.company and msg.company:
        tt.company = msg.company
        updated = True
    if not tt.sent_date and msg.timestamp:
        tt.sent_date = msg.timestamp.date()
        updated = True
    if not tt.ml_label and msg.ml_label:
        tt.ml_label = msg.ml_label
        updated = True
    if updated:
        tt.save()
        print(f"Updated ThreadTracking id={tt.id}")
    else:
        print("No updates applied to existing ThreadTracking")

print("Done")
