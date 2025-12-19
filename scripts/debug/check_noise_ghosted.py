import django

django.setup()

from tracker.models import ThreadTracking

# Find applications with status='ghosted' but ml_label='noise'
noise_ghosted = ThreadTracking.objects.filter(status="ghosted", ml_label="noise")
print(
    f"Applications with status='ghosted' but ml_label='noise': {noise_ghosted.count()}"
)
for app in noise_ghosted:
    print(f"  - {app.company.name} | sent: {app.sent_date}")

# These should be excluded from dashboard metrics now
