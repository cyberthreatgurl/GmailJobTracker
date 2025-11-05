import django

django.setup()

from tracker.models import Company, Application, Message
from django.utils.timezone import now
from datetime import timedelta

c = Company.objects.get(id=526)
print(f"Company: {c.name}")
print(f"Status: {c.status}")

apps = ThreadTracking.objects.filter(company_id=526)
print(f"\nApplications: {apps.count()}")
for app in apps:
    print(
        f"  - {app.job_title} | sent:{app.sent_date} | interview:{app.interview_date} | rejection:{app.rejection_date} | status:{app.status} | ml_label:{app.ml_label}"
    )

msgs = Message.objects.filter(company_id=526).order_by("-timestamp")
print(f"\nMessages (total {msgs.count()}):")
for msg in msgs[:10]:
    print(f"  - {msg.timestamp.date()} | {msg.ml_label} | {msg.subject[:80]}")

# Check rejections
rejections = ThreadTracking.objects.filter(company_id=526, rejection_date__isnull=False)
print(f"\nRejections in Applications: {rejections.count()}")

rejection_msgs = Message.objects.filter(
    company_id=526, ml_label__in=["rejected", "rejection"]
)
print(f"Rejection Messages: {rejection_msgs.count()}")

# Check last activity
cutoff_dt = now() - timedelta(days=30)
last_msg = msgs.first()
if last_msg:
    print(f"\nLast message date: {last_msg.timestamp}")
    print(f"Cutoff date (30 days ago): {cutoff_dt}")
    print(f"Last activity > cutoff? {last_msg.timestamp > cutoff_dt}")

