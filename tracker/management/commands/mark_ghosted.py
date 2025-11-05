"""Mark applications/messages as ghosted after inactivity.

Rules:
- Company-level first: If we receive a rejection from a company (any thread), do NOT
    count that company in the ghosted list.
- Otherwise, use the date of the last message sent/received with regards to the
    company (any thread) to determine inactivity. If no activity for N days (default 30),
    mark related applications as ghosted.

Behavior:
- Primary marking happens on Application (status='ghosted', ml_label='ghosted').
- Optionally sets a relevant pre-cutoff Message.ml_label to 'ghosted' (for charts).

Additional safeguards:
- Thread-level: If a rejection exists in the same thread (message labeled
    'rejected'/'rejection'), skip ghosting that thread (defensive).
- Headhunters: Companies labeled as headhunter are excluded from ghosted detection
    and counts.
- Noise: Applications labeled as noise are excluded from ghosted detection.

Configuration precedence for threshold days:
1) CLI option: --days N
2) AppSetting key 'GHOSTED_DAYS_THRESHOLD'
3) Env var GHOSTED_DAYS_THRESHOLD
4) Default: 30
"""

from datetime import timedelta
import os

from django.core.management.base import BaseCommand
from django.db.models import Q, Max
from django.utils.timezone import now

from tracker.models import AppSetting, ThreadTracking, Message, Company


def _get_threshold_days(cli_days: int | None) -> int:
    if cli_days and cli_days > 0:
        return cli_days
    # Try AppSetting
    try:
        s = AppSetting.objects.filter(key="GHOSTED_DAYS_THRESHOLD").first()
        if s:
            v = int(str(s.value).strip())
            if v > 0:
                return v
    except Exception:
        pass
    # Try env
    try:
        ev = os.environ.get("GHOSTED_DAYS_THRESHOLD")
        if ev:
            v = int(ev)
            if v > 0:
                return v
    except Exception:
        pass
    return 30


class Command(BaseCommand):
    help = "Mark Applications/Messages as ghosted after inactivity"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Days of inactivity after which to mark as ghosted (default 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Don't write changes, just print what would be updated",
        )

    def handle(self, *args, **kwargs):
        days = _get_threshold_days(kwargs.get("days"))
        cutoff_dt = now() - timedelta(days=days)
        dry_run = bool(kwargs.get("dry_run"))

        # Candidate applications: no rejection yet, and either
        # - sent_date <= cutoff, or
        # - interview_date <= cutoff
        app_candidates = (
            ThreadTracking.objects.filter(
                Q(rejection_date__isnull=True)
                & (
                    Q(sent_date__isnull=False, sent_date__lte=cutoff_dt.date())
                    | Q(
                        interview_date__isnull=False,
                        interview_date__lte=cutoff_dt.date(),
                    )
                )
            )
            .exclude(company__status="headhunter")
            .exclude(ml_label="noise")
            .select_related("company")
        )

        # Precompute companies that have sent rejections via Application or Message
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

        # We'll also consider message-based triggers in those threads
        total_apps_marked = 0
        total_msgs_marked = 0

        # Precompute last activity per company (latest message timestamp across all threads)
        last_activity_by_company = {
            row["company_id"]: row["last_ts"]
            for row in (
                Message.objects.exclude(company=None)
                .values("company_id")
                .annotate(last_ts=Max("timestamp"))
            )
        }

        for app in app_candidates:
            # Company-level guard: if this company has sent any rejection, skip
            if app.company_id in rejecting_companies:
                continue
            # Company-level guard: exclude headhunters entirely
            if app.company and app.company.status == "headhunter":
                continue
            # Thread-level defensive guard: if any rejection exists in this thread, skip
            if Message.objects.filter(
                thread_id=app.thread_id, ml_label__in=["rejected", "rejection"]
            ).exists():
                continue

            # Company-level last activity check
            last_ts = last_activity_by_company.get(app.company_id)
            if not last_ts:
                # Fall back to application/interview dates if no messages exist for the company
                last_date = None
                if app.sent_date:
                    last_date = app.sent_date
                if app.interview_date and (
                    not last_date or app.interview_date > last_date
                ):
                    last_date = app.interview_date
                if not last_date:
                    # No basis to evaluate inactivity
                    continue
                last_ts = now().__class__(
                    last_date.year, last_date.month, last_date.day, tzinfo=now().tzinfo
                )

            # If the company has had activity within the threshold, don't ghost
            if last_ts > cutoff_dt:
                continue

            # Mark the Application as ghosted
            if app.status != "ghosted" or app.ml_label != "ghosted":
                if not dry_run:
                    app.status = "ghosted"
                    app.ml_label = "ghosted"
                    app.reviewed = True
                    app.save(update_fields=["status", "ml_label", "reviewed"])
                total_apps_marked += 1

            # Also update the Company status to 'ghosted' (excluding headhunters)
            if app.company and app.company.status not in ("headhunter", "ghosted"):
                if not dry_run:
                    Company.objects.filter(id=app.company_id).update(status="ghosted")

            # Optionally mark the most recent pre-cutoff relevant message for charts
            trigger = (
                Message.objects.filter(
                    company_id=app.company_id,
                    timestamp__lte=cutoff_dt,
                    ml_label__in=["job_application", "interview_invite", "follow_up"],
                )
                .order_by("-timestamp")
                .first()
            )
            if trigger and trigger.ml_label != "ghosted":
                if not dry_run:
                    trigger.ml_label = "ghosted"
                    trigger.reviewed = True
                    trigger.save(update_fields=["ml_label", "reviewed"])
                total_msgs_marked += 1

            self.stdout.write(
                f"👻 Ghosted: {app.company.name} – {app.job_title} (last activity {last_ts.date()}, {days}d)"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Marked ghosted: applications={total_apps_marked}, messages={total_msgs_marked} (threshold={days}d, dry_run={dry_run})"
            )
        )
