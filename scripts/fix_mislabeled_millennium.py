"""Fix mislabeled Millennium messages."""

import os
import sys
import django

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

# Fix the Indeed Application message
indeed_msg = Message.objects.get(
    thread_id="19a56992c987cb4f", company__name="Millennium Corporation"
)

print(f"Fixing: {indeed_msg.subject}")
print(f"  Old label: {indeed_msg.ml_label}")

# This is an application confirmation, not an interview invite
indeed_msg.ml_label = "job_application"
indeed_msg.save()

print(f"  New label: {indeed_msg.ml_label}")
print()

# Delete the incorrect ThreadTracking record
thread = ThreadTracking.objects.filter(thread_id="19a56992c987cb4f").first()
if thread:
    print(f"✓ Deleting incorrect ThreadTracking for Indeed application")
    thread.delete()

# Show the correct remaining interview
print("\n" + "=" * 70)
print("MILLENNIUM CORPORATION UPCOMING INTERVIEWS")
print("=" * 70)

interviews = ThreadTracking.objects.filter(
    company__name="Millennium Corporation", interview_completed=False
).select_related("company")

print(f"\nFound {interviews.count()} actual interview(s):\n")
for t in interviews:
    print(f"  • {t.job_title}")
    print(f"    Thread ID: {t.thread_id}")
    print(f"    Date: {t.interview_date}")
    print(f"    ML Label: {t.ml_label}")
