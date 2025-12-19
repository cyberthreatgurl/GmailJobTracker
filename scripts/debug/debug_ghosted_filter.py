import django

django.setup()

from datetime import timedelta

from django.db.models import Q
from django.utils.timezone import now

from tracker.models import Message

days = 30
cutoff_dt = now() - timedelta(days=days)

# Exactly replicate the ghosted command query
app_candidates = (
    ThreadTracking.objects.filter(
        Q(rejection_date__isnull=True)
        & (
            Q(sent_date__isnull=False, sent_date__lte=cutoff_dt.date())
            | Q(interview_date__isnull=False, interview_date__lte=cutoff_dt.date())
        )
    )
    .exclude(company__status="headhunter")
    .select_related("company")
)

# Check if Home Depot is in candidates
home_depot_apps = app_candidates.filter(company_id=526)
print(f"Home Depot in candidates: {home_depot_apps.count()}")
for app in home_depot_apps:
    print(
        f"  App: {app.id} | sent:{app.sent_date} | status:{app.status} | ml_label:{app.ml_label}"
    )

# Check rejecting companies
rejecting_companies = set(
    ThreadTracking.objects.filter(rejection_date__isnull=False)
    .values_list("company_id", flat=True)
    .distinct()
)
msg_rejecting_companies = set(
    Message.objects.filter(ml_label__in=["rejected", "rejection"])
    .exclude(company=None)
    .values_list("company_id", flat=True)
    .distinct()
)
rejecting_companies.update(msg_rejecting_companies)

print(f"\n526 in rejecting_companies? {526 in rejecting_companies}")

# Check last activity
from django.db.models import Max

last_activity_by_company = {
    row["company_id"]: row["last_ts"]
    for row in (
        Message.objects.exclude(company=None)
        .values("company_id")
        .annotate(last_ts=Max("timestamp"))
    )
}

print(f"\nLast activity for 526: {last_activity_by_company.get(526)}")
print(f"Cutoff: {cutoff_dt}")
if 526 in last_activity_by_company:
    print(f"Last activity > cutoff? {last_activity_by_company[526] > cutoff_dt}")
