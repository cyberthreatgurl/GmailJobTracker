import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message, Company

c = Company.objects.filter(name__icontains="Endyna").first()
print(f"Company: {c.name} (ID: {c.id})")

print("\n=== All ThreadTracking records for Endyna: ===")
all_tt = ThreadTracking.objects.filter(company=c)
print(f"Total ThreadTracking records: {all_tt.count()}")
for t in all_tt:
    print(f"  Thread {t.thread_id}:")
    print(f"    interview_date: {t.interview_date}")
    print(f"    sent_date: {t.sent_date}")
    print(f"    rejection_date: {t.rejection_date}")
    print(f"    ml_label: {t.ml_label}")

print("\n=== Messages for thread 0455 (interview_invite with no ThreadTracking): ===")
msgs_0455 = Message.objects.filter(thread_id="19a697805f150455")
print(f"Count: {msgs_0455.count()}")
for m in msgs_0455:
    print(f"  Message {m.msg_id}:")
    print(f"    ml_label: {m.ml_label}")
    print(f"    company: {m.company}")
    print(f"    subject: {m.subject}")
    print(f"    timestamp: {m.timestamp}")

print("\n=== Checking if ThreadTracking exists for thread 0455: ===")
tt_0455 = ThreadTracking.objects.filter(thread_id="19a697805f150455").first()
if tt_0455:
    print(
        f"  Found: interview_date={tt_0455.interview_date}, company={tt_0455.company}"
    )
else:
    print("  No ThreadTracking record found for thread 0455")
