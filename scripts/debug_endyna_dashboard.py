import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message, Company
from datetime import datetime, timedelta

c = Company.objects.filter(name__icontains="Endyna").first()
print(f"Company: {c.name} (ID: {c.id})")

print("\n=== 1. ThreadTracking with interview_date ===")
tt_interviews = ThreadTracking.objects.filter(
    interview_date__isnull=False, company__isnull=False, company=c
).order_by("interview_date")

interview_companies = []
for t in tt_interviews:
    print(f"Thread {t.thread_id[:16]}: interview_date={t.interview_date}")
    interview_companies.append(
        {
            "company_id": c.id,
            "company__name": c.name,
            "interview_date": t.interview_date.strftime("%Y-%m-%d"),
            "source": "ThreadTracking",
            "thread_id": t.thread_id,
        }
    )

print(f"\nThreadTracking count: {len(interview_companies)}")

print("\n=== 2. Build tracked (thread_id, company_id) set ===")
tt_with_interview = ThreadTracking.objects.filter(
    interview_date__isnull=False, company__isnull=False
).values("thread_id", "company_id")

tracked_thread_companies = {
    (item["thread_id"], item["company_id"]) for item in tt_with_interview
}
print(f"Total tracked combinations: {len(tracked_thread_companies)}")
print(
    f"Endyna tracked threads: {[t for t, c_id in tracked_thread_companies if c_id == c.id]}"
)

print("\n=== 3. Interview_invite messages ===")
msg_interviews = (
    Message.objects.filter(
        ml_label="interview_invite", company__isnull=False, company=c
    )
    .select_related("company")
    .order_by("timestamp")
)

print(f"Total interview_invite messages for Endyna: {msg_interviews.count()}")

added_count = 0
for msg in msg_interviews:
    is_tracked = (msg.thread_id, msg.company_id) in tracked_thread_companies
    print(f"\nThread {msg.thread_id[:16]}: timestamp={msg.timestamp.date()}")
    print(f"  Subject: {msg.subject[:60]}")
    print(f"  Tracked: {is_tracked}")

    if not is_tracked:
        interview_companies.append(
            {
                "company_id": msg.company_id,
                "company__name": msg.company.name,
                "interview_date": msg.timestamp.strftime("%Y-%m-%d"),
                "source": "Message",
                "thread_id": msg.thread_id,
            }
        )
        added_count += 1
        print(f"  ✓ ADDED to interview_companies")
    else:
        print(f"  ✗ SKIPPED (already tracked)")

print(f"\n=== FINAL COUNT ===")
print(
    f'ThreadTracking: {len([x for x in interview_companies if x["source"] == "ThreadTracking"])}'
)
print(f"Messages added: {added_count}")
print(f"TOTAL: {len(interview_companies)}")

print("\n=== All entries by date ===")
for item in sorted(interview_companies, key=lambda x: x["interview_date"]):
    print(
        f'{item["interview_date"]} - {item["source"]} - thread {item["thread_id"][:16]}'
    )

# Check date range filtering (dashboard shows last 90 days by default)
today = datetime.now().date()
days_90_ago = today - timedelta(days=90)
print(f"\n=== Date range check (last 90 days: {days_90_ago} to {today}) ===")
in_range = [
    x
    for x in interview_companies
    if datetime.strptime(x["interview_date"], "%Y-%m-%d").date() >= days_90_ago
]
print(f"Entries in last 90 days: {len(in_range)}")
for item in in_range:
    print(f'  {item["interview_date"]} - {item["source"]}')
