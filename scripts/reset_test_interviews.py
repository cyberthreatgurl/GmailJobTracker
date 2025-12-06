"""Reset recent interview records for testing."""
import os
import sys
import django
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import ThreadTracking

# Reset interviews with date 2025-11-15 to not completed
reset_count = ThreadTracking.objects.filter(
    interview_date=date(2025, 11, 15)
).update(interview_completed=False)

print(f"✓ Reset {reset_count} interviews to 'not completed'")

# Show upcoming interviews
upcoming = ThreadTracking.objects.filter(
    interview_date__gte=date(2025, 11, 8),
    interview_completed=False,
    company__isnull=False
).select_related("company")

print(f"\n📅 Upcoming Interviews ({upcoming.count()}):")
for t in upcoming:
    job_title = t.job_title or "(no title)"
    print(f"  • {t.company.name}: {job_title[:50]} on {t.interview_date}")

print("\n✅ Dashboard 'Upcoming Interviews' box will now show these records!")
