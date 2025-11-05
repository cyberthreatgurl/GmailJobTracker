import django

django.setup()

from tracker.models import ThreadTracking
from django.db.models import Q

ghosted_qs = (
    ThreadTracking.objects.filter(
        Q(status="ghosted") | Q(ml_label="ghosted"), company__isnull=False
    )
    .select_related("company")
    .values("company_id", "company__name", "sent_date")
    .order_by("-sent_date")
)

print(f"Total ghosted applications: {ghosted_qs.count()}")
print("\nFirst 10:")
for g in list(ghosted_qs)[:10]:
    print(f"  {g}")

# Check if The Home Depot is in the results
home_depot = [g for g in ghosted_qs if "Home Depot" in str(g.get("company__name", ""))]
print(f"\nThe Home Depot in results: {len(home_depot)}")
if home_depot:
    print(f"  {home_depot[0]}")

