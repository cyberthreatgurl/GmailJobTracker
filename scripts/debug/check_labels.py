import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message

# Check what's in ml_label field
msgs = Message.objects.filter(reviewed=True, ml_label__isnull=False)[:20]

print("Sample messages with ml_label:")
print("-" * 80)
for m in msgs:
    company_name = m.company.name if m.company else "None"
    print(f"Company: {company_name:30} | ml_label: {m.ml_label}")

print("\n" + "-" * 80)
print(f"Total reviewed messages: {Message.objects.filter(reviewed=True).count()}")
print(f"Total with ml_label: {Message.objects.filter(ml_label__isnull=False).count()}")
