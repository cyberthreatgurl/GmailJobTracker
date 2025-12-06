"""Show final upcoming interviews list."""
import os
import sys
import django

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking

upcoming = ThreadTracking.objects.filter(
    interview_date__gte='2025-11-08',
    interview_completed=False,
    company__isnull=False
).select_related('company').order_by('interview_date')

print("=" * 70)
print("📅 UPCOMING INTERVIEWS - DASHBOARD VIEW")
print("=" * 70)
print(f"\nTotal: {upcoming.count()} interview(s)\n")

for i, t in enumerate(upcoming, 1):
    job_title = t.job_title or "(no title)"
    print(f"{i}. {t.company.name}: {job_title}")
    print(f"   Date: {t.interview_date}")
    print(f"   Status: {'✅ Completed' if t.interview_completed else '⏳ Pending'}")
    print()
