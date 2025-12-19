import sys

sys.path.insert(0, r"C:\Users\kaver\code\GmailJobTracker")
import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()
from tracker.models import Message, ThreadTracking

mid = "0101019976e7cd16-fe5f3230-f899-4277-beb0-363318a947d9-000000@us-west-2.amazonses.com"
msg = Message.objects.filter(msg_id=mid).first()
print(
    "Message:",
    msg and msg.id,
    "ml_label=",
    getattr(msg, "ml_label", None),
    "confidence=",
    getattr(msg, "confidence", None),
)
if msg:
    tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
    print(
        "ThreadTracking:",
        tt and tt.id,
        "ml_label=",
        getattr(tt, "ml_label", None),
        "ml_confidence=",
        getattr(tt, "ml_confidence", None),
        "status=",
        getattr(tt, "status", None),
    )
else:
    print("Message not found")
