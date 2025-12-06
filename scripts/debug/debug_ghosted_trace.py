import django

django.setup()

from datetime import timedelta

from django.db.models import Max
from django.utils.timezone import now

from tracker.models import Message

days = 30
cutoff_dt = now() - timedelta(days=days)

app = ThreadTracking.objects.get(id=564)  # The Home Depot application
print(f"Processing app {app.id}: {app.company.name}")

# Check 1: Company-level guard: if this company has sent any rejection, skip
rejecting_companies = set(
    ThreadTracking.objects.filter(rejection_date__isnull=False)
    .values_list("company_id", flat=True)
    .distinct()
)
msg_rejecting_companies = set(
    Message.objects.filter(ml_label__in=["rejected", "rejection"])
    .exclude(company=None)
    .values_list("company_id", flat=True)
    .distinct()
)
rejecting_companies.update(msg_rejecting_companies)

if app.company_id in rejecting_companies:
    print("  ❌ SKIP: Company has sent rejections")
else:
    print("  ✅ PASS: No rejections from company")

# Check 2: Company-level guard: exclude headhunters entirely
if app.company and app.company.status == "headhunter":
    print("  ❌ SKIP: Company is headhunter")
else:
    print(f"  ✅ PASS: Not headhunter (status={app.company.status})")

# Check 3: Thread-level defensive guard
thread_rejection = Message.objects.filter(
    thread_id=app.thread_id, ml_label__in=["rejected", "rejection"]
).exists()
if thread_rejection:
    print("  ❌ SKIP: Thread has rejection message")
else:
    print("  ✅ PASS: No rejection in thread")

# Check 4: Company-level last activity check
last_activity_by_company = {
    row["company_id"]: row["last_ts"]
    for row in (
        Message.objects.exclude(company=None)
        .values("company_id")
        .annotate(last_ts=Max("timestamp"))
    )
}

last_ts = last_activity_by_company.get(app.company_id)
print(f"\n  Last activity: {last_ts}")
print(f"  Cutoff: {cutoff_dt}")

if not last_ts:
    print("  Using fallback to application dates")
    last_date = app.sent_date if app.sent_date else None
    if app.interview_date and (not last_date or app.interview_date > last_date):
        last_date = app.interview_date
    if not last_date:
        print("  ❌ SKIP: No activity date found")
    else:
        last_ts = now().__class__(
            last_date.year, last_date.month, last_date.day, tzinfo=now().tzinfo
        )
        print(f"  Fallback last_ts: {last_ts}")

if last_ts and last_ts > cutoff_dt:
    print("  ❌ SKIP: Recent activity within threshold")
else:
    print("  ✅ PASS: No recent activity, should be GHOSTED")

print(f"\n  Current app.status: '{app.status}'")
print(f"  Current app.ml_label: '{app.ml_label}'")
print(f"  Current company.status: '{app.company.status}'")

