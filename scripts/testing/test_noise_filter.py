import django

django.setup()

from django.db.models import Q

from tracker.models import ThreadTracking

# Replicate the updated ghosted query
ghosted_qs = (
    ThreadTracking.objects.filter(
        Q(status="ghosted") | Q(ml_label="ghosted"), company__isnull=False
    )
    .exclude(ml_label="noise")
    .select_related("company")
    .values("company_id", "company__name", "sent_date")
    .order_by("-sent_date")
)

print(f"Ghosted applications (excluding noise): {ghosted_qs.count()}")
print("\nFirst 10:")
for g in list(ghosted_qs)[:10]:
    print(f"  {g}")

# Compare to the old query (without noise exclusion)
old_qs = (
    ThreadTracking.objects.filter(
        Q(status="ghosted") | Q(ml_label="ghosted"), company__isnull=False
    )
    .select_related("company")
    .values("company_id", "company__name", "sent_date")
    .order_by("-sent_date")
)

print(f"\nOld query count (with noise): {old_qs.count()}")
print(f"Difference: {old_qs.count() - ghosted_qs.count()} applications filtered out")
