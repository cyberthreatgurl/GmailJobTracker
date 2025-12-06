"""Check Millennium Corporation messages and thread tracking."""
import os
import sys
import django

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Check Messages
print("=" * 70)
print("MILLENNIUM CORPORATION MESSAGES")
print("=" * 70)
msgs = Message.objects.filter(company__name='Millennium Corporation')
print(f"\nFound {msgs.count()} message(s)\n")

for m in msgs[:10]:
    print(f"Subject: {m.subject}")
    print(f"ML Label: {m.ml_label}")
    print(f"Confidence: {m.confidence}")
    print(f"Thread ID: {m.thread_id}")
    print(f"Timestamp: {m.timestamp}")
    print(f"Sender: {m.sender}")
    print()

# Check ThreadTracking
print("=" * 70)
print("MILLENNIUM CORPORATION THREAD TRACKING")
print("=" * 70)
threads = ThreadTracking.objects.filter(company__name='Millennium Corporation')
print(f"\nFound {threads.count()} thread(s)\n")

for t in threads[:10]:
    print(f"Job Title: {t.job_title}")
    print(f"ML Label: {t.ml_label}")
    print(f"Status: {t.status}")
    print(f"Thread ID: {t.thread_id}")
    print(f"Interview Date: {t.interview_date}")
    print(f"Interview Completed: {t.interview_completed}")
    print()

# Check if there are orphaned messages (Message exists but no ThreadTracking)
if msgs.count() > 0 and threads.count() == 0:
    print("⚠️  WARNING: Message(s) exist but no ThreadTracking record!")
    print("   This means the message was ingested but didn't create an application record.")
    print("\n   Possible reasons:")
    print("   - Message classified as 'noise' or 'headhunter'")
    print("   - Message is a follow-up in an existing thread (not first message)")
    print("   - Error during ThreadTracking creation")
