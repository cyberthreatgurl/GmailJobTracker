import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking, Message, Company

c = Company.objects.filter(name__icontains="Endyna").first()
print(f"Company: {c.name} (ID: {c.id})")

print("\n=== ThreadTracking with interview_date: ===")
tt_interviews = ThreadTracking.objects.filter(company=c, interview_date__isnull=False)
print(f"Count: {tt_interviews.count()}")
for t in tt_interviews:
    print(f"  Thread {t.thread_id}: interview_date={t.interview_date}")

print("\n=== Messages with interview_invite label: ===")
msg_interviews = Message.objects.filter(company=c, ml_label="interview_invite")
print(f"Count: {msg_interviews.count()}")
for m in msg_interviews:
    print(f"  Thread {m.thread_id}: timestamp={m.timestamp}")
    print(f"    Subject: {m.subject[:80]}")

print("\n=== Checking overlap: ===")
tt_thread_ids = set(tt_interviews.values_list("thread_id", flat=True))
msg_thread_ids = set(msg_interviews.values_list("thread_id", flat=True))
print(f"ThreadTracking thread_ids: {tt_thread_ids}")
print(f"Message thread_ids: {msg_thread_ids}")
print(f"Overlap: {tt_thread_ids & msg_thread_ids}")
print(f"Messages NOT in ThreadTracking: {msg_thread_ids - tt_thread_ids}")
