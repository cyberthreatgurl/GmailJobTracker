"""Debug why Endyna interview isn't showing on dashboard."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, ThreadTracking, Message
from datetime import date

# Get Endyna company
c = Company.objects.get(id=493)
print(f"Company: {c.name}")
print(f"Status: {c.status}")
print(f"Domain: {c.domain}")

# Check ThreadTracking records
apps = ThreadTracking.objects.filter(company_id=493)
print(f"\nThreadTracking records: {apps.count()}")
for a in apps:
    print(f"  id={a.id} thread={a.thread_id}")
    print(f"    interview_date={a.interview_date}")
    print(f"    rejection_date={a.rejection_date}")
    print(f"    status={a.status}")
    print(f"    ml_label={a.ml_label}")
    print(f"    job_title={a.job_title}")

# Check messages
msgs = Message.objects.filter(company_id=493).order_by("timestamp")
print(f"\nMessages: {msgs.count()}")
for m in msgs:
    print(f"  id={m.id} ts={m.timestamp.date()} label={m.ml_label}")
    print(f"    subject: {m.subject[:80]}")

# Check the dashboard query for interviews
print("\n--- Dashboard Interview Query ---")
from django.db.models import Q

interview_query = (
    ThreadTracking.objects.filter(interview_date__isnull=False)
    .exclude(
        Q(status="ghosted") | Q(status="rejected") | Q(rejection_date__isnull=False)
    )
    .exclude(company__status="headhunter")
)

print(f"Total interviews (excluding ghosted/rejected): {interview_query.count()}")

endyna_in_query = interview_query.filter(company_id=493)
print(f"Endyna in interview query: {endyna_in_query.count()}")
if endyna_in_query.exists():
    for app in endyna_in_query:
        print(f"  ✅ Found: id={app.id} interview_date={app.interview_date}")
else:
    print("  ❌ Endyna NOT in interview query")

    # Check why it's excluded
    endyna_apps = ThreadTracking.objects.filter(
        company_id=493, interview_date__isnull=False
    )
    for app in endyna_apps:
        print(f"\n  Checking app id={app.id}:")
        print(f"    interview_date: {app.interview_date}")
        print(f"    status: {app.status}")
        print(f"    rejection_date: {app.rejection_date}")
        print(f"    company.status: {app.company.status}")

        if app.status == "ghosted":
            print(f"    ❌ EXCLUDED: status is 'ghosted'")
        if app.status == "rejected":
            print(f"    ❌ EXCLUDED: status is 'rejected'")
        if app.rejection_date:
            print(f"    ❌ EXCLUDED: has rejection_date")
        if app.company.status == "headhunter":
            print(f"    ❌ EXCLUDED: company is headhunter")
