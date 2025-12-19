import sys
import os

sys.path.insert(0, r"C:\Users\kaver\code\GmailJobTracker")
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking

# Try to find a ThreadTracking created for the 2025-11-21 application
tt = ThreadTracking.objects.filter(sent_date="2025-11-21").order_by("-id").first()
if not tt:
    print("No ThreadTracking found for sent_date=2025-11-21")
else:
    print("ThreadTracking found:")
    print("id:", tt.id)
    print("thread_id:", tt.thread_id)
    print("company:", tt.company.name if tt.company else None)
    print("sent_date:", tt.sent_date)
    print("job_title:", tt.job_title)
    print("status:", tt.status)
    print("ml_label:", tt.ml_label, "ml_confidence:", tt.ml_confidence)
