import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, Company

c = Company.objects.filter(name__icontains="Endyna").first()

print("=== All Endyna messages labeled as interview_invite ===")
msgs = Message.objects.filter(company=c, ml_label="interview_invite").order_by(
    "timestamp"
)

for m in msgs:
    print(f"\nTimestamp: {m.timestamp}")
    print(f"Subject: {m.subject}")
    print(f"Confidence: {m.confidence}")
    print(f"Body snippet: {m.body[:300]}...")
    print("-" * 80)
