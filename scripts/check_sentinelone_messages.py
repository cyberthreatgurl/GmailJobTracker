import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Message, Company, ThreadTracking

qs = Message.objects.filter(company__name__icontains="SentinelOne")
print("Total messages for companies matching SentinelOne:", qs.count())
for m in qs.order_by("-timestamp")[:50]:
    print(
        m.id,
        m.msg_id,
        m.thread_id,
        m.timestamp,
        m.ml_label,
        m.company.name if m.company else None,
        (m.subject or "")[:120],
    )

# Also list any ThreadTracking with company SentinelOne
tt = ThreadTracking.objects.filter(
    company__name__icontains="SentinelOne", interview_date__isnull=False
)
print("ThreadTracking with interview_date for SentinelOne:", tt.count())
for t in tt:
    print("TT:", t.id, t.thread_id, t.interview_date, t.ml_label, t.status)
