import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message, Company

c = Company.objects.filter(name__icontains="Endyna").first()
print(f"Company: {c.name} (ID: {c.id})")

# Replicate the exact logic from views.py
print("\n=== Step 1: ThreadTracking with interview_date ===")
interview_companies_qs = ThreadTracking.objects.filter(
    interview_date__isnull=False, company__isnull=False, company=c
).values("company_id", "company__name", "interview_date", "thread_id")

interview_companies = []
for item in interview_companies_qs:
    interview_companies.append(
        {
            "company_id": item["company_id"],
            "company__name": item["company__name"],
            "interview_date": item["interview_date"].strftime("%Y-%m-%d"),
            "source": "ThreadTracking",
            "thread_id": item["thread_id"],
        }
    )
    print(f'  Added: thread={item["thread_id"]}, date={item["interview_date"]}')

print(f"\nThreadTracking count: {len(interview_companies)}")

print("\n=== Step 2: Build tracked (thread_id, company_id) set ===")
tt_with_interview = ThreadTracking.objects.filter(
    interview_date__isnull=False, company__isnull=False
).values("thread_id", "company_id")

tracked_thread_companies = {
    (item["thread_id"], item["company_id"]) for item in tt_with_interview
}
print(f"Total tracked combinations: {len(tracked_thread_companies)}")
for thread_id, company_id in tracked_thread_companies:
    if company_id == c.id:
        print(f"  Endyna: ({thread_id}, {company_id})")

print("\n=== Step 3: Interview_invite messages ===")
msg_interviews_qs = Message.objects.filter(
    ml_label="interview_invite", company__isnull=False, company=c
).select_related("company")

print(f"Total interview_invite messages for Endyna: {msg_interviews_qs.count()}")

added_count = 0
for msg in msg_interviews_qs:
    is_tracked = (msg.thread_id, msg.company_id) in tracked_thread_companies
    print(f"  Thread {msg.thread_id}: tracked={is_tracked}, timestamp={msg.timestamp}")
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
        print(f"    ✓ ADDED to interview_companies")
    else:
        print(f"    ✗ SKIPPED (already tracked)")

print(f"\n=== Final Result ===")
print(
    f'ThreadTracking entries: {len([x for x in interview_companies if x["source"] == "ThreadTracking"])}'
)
print(f"Message entries added: {added_count}")
print(f"TOTAL for Endyna: {len(interview_companies)}")
print("\nAll entries:")
for item in sorted(interview_companies, key=lambda x: x["interview_date"]):
    print(
        f'  {item["interview_date"]} - {item["source"]} - thread={item["thread_id"][:10]}...'
    )
