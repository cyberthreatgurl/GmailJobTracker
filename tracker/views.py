from django.contrib.auth.decorators import login_required
from django.contrib import messages
from tracker.models import (
    Company,
    Application,
    Message,
    IngestionStats,
    UnresolvedCompany,
)
from datetime import timedelta, datetime
from collections import defaultdict
from tracker.forms import ApplicationEditForm
from pathlib import Path
import subprocess
import sys
from db import PATTERNS_PATH
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.timezone import now
import os
from django.db import models
from django.db.models import (
    F,
    Q,
    Count,
    Case,
    When,
    Value,
    IntegerField,
    CharField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Substr, StrIndex
from bs4 import BeautifulSoup
import json
import re
import html


# --- Re-ingestion Admin Page ---
@login_required
@require_http_methods(["GET", "POST"])
def reingest_admin(request):
    import os
    import subprocess
    import sys
    from datetime import datetime

    # For dropdown
    DAY_CHOICES = [
        (1, "1 day"),
        (7, "7 days"),
        (14, "14 days"),
        (30, "30 days"),
        (60, "60 days"),
        (90, "90 days"),
        (99999, "ALL since REPORTING_DEFAULT_START_DATE"),
    ]
    default_days = 7
    reporting_default_start_date = os.environ.get(
        "REPORTING_DEFAULT_START_DATE", "2025-02-15"
    )
    # Defaults
    result = None
    before_metrics = None
    after_metrics = None
    error = None
    if request.method == "POST":
        # Parse form
        days_back = int(request.POST.get("days_back", default_days))
        force = bool(request.POST.get("force"))
        reparse_all = bool(request.POST.get("reparse_all"))
        metrics_before = True
        metrics_after = True
        # Build command
        cmd = [sys.executable, "manage.py", "ingest_gmail"]
        if days_back == 99999:
            # Calculate days since REPORTING_DEFAULT_START_DATE
            try:
                dt = datetime.strptime(
                    reporting_default_start_date.replace('"', ""), "%Y-%m-%d"
                )
                delta = (datetime.now() - dt).days
                cmd += ["--days-back", str(delta)]
            except Exception:
                cmd += ["--days-back", "90"]
        else:
            cmd += ["--days-back", str(days_back)]
        if force:
            cmd.append("--force")
        if reparse_all:
            cmd.append("--reparse-all")
        if metrics_before:
            cmd.append("--metrics-before")
        if metrics_after:
            cmd.append("--metrics-after")
        # Run command and capture output
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, encoding="utf-8"
            )
            result = proc.stdout + "\n" + proc.stderr
        except Exception as e:
            error = str(e)
    ctx = build_sidebar_context()
    ctx.update(
        {
            "day_choices": DAY_CHOICES,
            "default_days": default_days,
            "reporting_default_start_date": reporting_default_start_date,
            "result": result,
            "error": error,
        }
    )
    return render(request, "tracker/reingest_admin.html", ctx)


from django.contrib.auth.decorators import login_required
from django.contrib import messages
from tracker.models import (
    Company,
    Application,
    Message,
    IngestionStats,
    UnresolvedCompany,
)
from datetime import timedelta, datetime
from collections import defaultdict
from tracker.forms import ApplicationEditForm
from pathlib import Path
import subprocess
import sys
from db import PATTERNS_PATH
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
import os
from django.db import models
from django.db.models import (
    F,
    Q,
    Count,
    Case,
    When,
    Value,
    IntegerField,
    CharField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Substr, StrIndex
from bs4 import BeautifulSoup


# --- Delete Company Page ---
@login_required
def delete_company(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    if request.method == "POST":
        company_name = company.name

        # Count related data before deletion
        message_count = Message.objects.filter(company=company).count()
        application_count = Application.objects.filter(company=company).count()

        # Delete all related messages, applications, etc.
        Message.objects.filter(company=company).delete()
        Application.objects.filter(company=company).delete()
        # Remove company itself
        company.delete()

        # Show detailed deletion info
        messages.success(request, f"✅ Company '{company_name}' deleted successfully.")
        messages.info(
            request,
            f"📊 Removed {message_count} messages and {application_count} applications.",
        )

        # Trigger model retraining in background
        messages.info(request, "🔄 Retraining model to update training data...")
        try:
            result = subprocess.run(
                [python_path, "train_model.py"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0:
                messages.success(
                    request, "✅ Model retrained successfully. Training data updated."
                )
            else:
                messages.warning(
                    request,
                    f"⚠️ Model retraining encountered issues. You may need to retrain manually.",
                )
        except subprocess.TimeoutExpired:
            messages.warning(
                request,
                "⚠️ Model retraining timed out. Please retrain manually from the sidebar.",
            )
        except Exception as e:
            messages.warning(
                request,
                f"⚠️ Could not auto-retrain model: {str(e)}. Please retrain manually.",
            )

        return redirect("label_companies")
    ctx = {"company": company}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/delete_company.html", ctx)


from django.contrib.auth.decorators import login_required
from .forms_company import CompanyEditForm


# --- Label Companies Page ---
@login_required
def label_companies(request):
    companies = Company.objects.order_by("name")
    selected_id = request.GET.get("company")
    selected_company = None
    latest_label = None
    form = None
    message_count = 0
    message_info_list = []
    if selected_id:
        try:
            selected_company = companies.get(id=selected_id)
        except Company.DoesNotExist:
            selected_company = None
        if selected_company:
            # Get latest label from messages
            latest_msg = (
                Message.objects.filter(company=selected_company, ml_label__isnull=False)
                .order_by("-timestamp")
                .first()
            )
            latest_label = latest_msg.ml_label if latest_msg else None
            # Get message count and (date, subject) list
            messages_qs = Message.objects.filter(company=selected_company).order_by(
                "-timestamp"
            )
            message_count = messages_qs.count()
            message_info_list = list(messages_qs.values_list("timestamp", "subject"))
            if request.method == "POST":
                form = CompanyEditForm(request.POST, instance=selected_company)
                if form.is_valid():
                    form.save()
            else:
                form = CompanyEditForm(instance=selected_company)

    ctx = build_sidebar_context()
    ctx.update(
        {
            "company_list": companies,
            "selected_company": selected_company,
            "form": form,
            "latest_label": latest_label,
            "message_count": message_count,
            "message_info_list": message_info_list,
        }
    )
    return render(request, "tracker/label_companies.html", ctx)


from tracker.models import (
    Company,
    Application,
    Message,
    IngestionStats,
    UnresolvedCompany,
)


from datetime import timedelta
from collections import defaultdict

from tracker.forms import ApplicationEditForm
from pathlib import Path
import subprocess
import sys
from db import PATTERNS_PATH
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
import os
from datetime import datetime
from django.db import models
from django.db.models import (
    F,
    Q,
    Count,
    Case,
    When,
    Value,
    IntegerField,
    CharField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Substr, StrIndex
from bs4 import BeautifulSoup

python_path = sys.executable
ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")


def build_sidebar_context():
    companies_count = Company.objects.count()
    applications_count = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()
    return {
        "companies": companies_count,
        "applications": applications_count,
        "rejections_week": rejections_week,
        "interviews_week": interviews_week,
        "upcoming_interviews": upcoming_interviews,
        "latest_stats": latest_stats,
    }


@login_required
@login_required
def company_threads(request):
    # Get all reviewed companies (at least one reviewed message)
    reviewed_company_ids = (
        Message.objects.filter(reviewed=True, company__isnull=False)
        .values_list("company_id", flat=True)
        .distinct()
    )
    companies = Company.objects.filter(id__in=reviewed_company_ids).order_by("name")

    selected_company_id = request.GET.get("company")
    selected_company = None
    threads_by_subject = []
    if selected_company_id:
        try:
            selected_company = companies.get(id=selected_company_id)
        except Company.DoesNotExist:
            selected_company = None
        if selected_company:
            # Group messages by subject for this company, only reviewed
            msgs = Message.objects.filter(
                company=selected_company, reviewed=True
            ).order_by("thread_id", "timestamp")
            # subject -> list of threads (each thread is a list of messages)
            threads = defaultdict(list)
            for msg in msgs:
                threads[msg.subject].append(msg)
            # Each subject: list of messages (thread)
            threads_by_subject = [
                {"subject": subj, "messages": thread}
                for subj, thread in threads.items()
            ]

    # Sidebar context
    companies_count = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/company_threads.html",
        {
            "companies": companies_count,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "company_list": companies,
            "selected_company": selected_company,
            "threads_by_subject": threads_by_subject,
        },
    )


@login_required
def manage_aliases(request):
    if not ALIAS_EXPORT_PATH.exists():
        ctx = {"suggestions": []}
        ctx.update(build_sidebar_context())
        return render(request, "tracker/manage_aliases.html", ctx)

    with open(ALIAS_EXPORT_PATH, "r", encoding="utf-8") as f:
        suggestions = json.load(f)

    ctx = {"suggestions": suggestions}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/manage_aliases.html", ctx)


@csrf_exempt
def approve_bulk_aliases(request):
    if request.method == "POST":
        aliases = request.POST.getlist("alias")
        suggested = request.POST.getlist("suggested")

        # Load patterns
        if PATTERNS_PATH.exists():
            with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
                patterns = json.load(f)
        else:
            patterns = {"aliases": {}, "ignore": []}

        for alias, suggestion in zip(aliases, suggested):
            patterns["aliases"][alias] = suggestion
            with open(ALIAS_LOG_PATH, "a", encoding="utf-8") as log:
                log.write(f"{alias},{suggestion},{request.POST.get('timestamp')}\n")

        with open(PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2)

        return redirect("manage_aliases")


@csrf_exempt
def reject_alias(request):
    if request.method == "POST":
        alias = request.POST.get("alias")

        # Load patterns
        if PATTERNS_PATH.exists():
            with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
                patterns = json.load(f)
        else:
            patterns = {"aliases": {}, "ignore": []}

        if alias not in patterns["ignore"]:
            patterns["ignore"].append(alias)

        with open(PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2)

        with open(ALIAS_REJECT_LOG_PATH, "a", encoding="utf-8") as log:
            log.write(f"{alias},{request.POST.get('timestamp')}\n")

        return redirect("manage_aliases")


def edit_application(request, pk):
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        form = ApplicationEditForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect("flagged_applications")
    else:
        form = ApplicationEditForm(instance=app)
    return render(request, "tracker/edit.html", {"form": form})


def flagged_applications(request):
    flagged = Application.objects.filter(
        models.Q(company="")
        | models.Q(company_source__in=["none", "ml_prediction", "sender_name_match"])
    ).order_by("-first_sent")[:100]

    return render(request, "tracker/flagged.html", {"applications": flagged})


@login_required
def dashboard(request):
    def clean_html(raw_html):
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return str(soup)

    companies = Company.objects.count()
    companies_list = Company.objects.all()
    unresolved_companies = UnresolvedCompany.objects.filter(reviewed=False).order_by(
        "-timestamp"
    )[:50]

    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")

    # ✅ Recent messages with company preloaded
    messages = Message.objects.select_related("company").order_by("-timestamp")[:100]
    for msg in messages:
        raw_html = msg.body or ""
        msg.cleaned_body_html = extract_body_content(raw_html)

    # ✅ Group messages by thread_id with company preloaded
    threads = defaultdict(list)
    seen = set()

    for msg in Message.objects.select_related("company").order_by(
        "thread_id", "timestamp"
    ):
        if msg.msg_id not in seen:
            threads[msg.thread_id].append(msg)
            seen.add(msg.msg_id)

    # ✅ Filter to threads with >1 message, then sort and slice
    thread_list = sorted(
        [(tid, msgs) for tid, msgs in threads.items() if len(msgs) > 1],
        key=lambda t: t[1][-1].timestamp,
        reverse=True,
    )[:50]

    #  Ingestion stats
    latest_stats = IngestionStats.objects.order_by("-date").first()
    ingested_today = latest_stats.total_inserted if latest_stats else 0
    ignored_today = latest_stats.total_ignored if latest_stats else 0
    skipped_today = latest_stats.total_skipped if latest_stats else 0

    # Ingestion plot: start at earliest activity date
    earliest_stat = IngestionStats.objects.order_by("date").first()
    if earliest_stat:
        start_date = earliest_stat.date
        end_date = now().date()
        num_days = (end_date - start_date).days + 1
        date_list = [start_date + timedelta(days=i) for i in range(num_days)]
        stats_qs = IngestionStats.objects.filter(date__gte=start_date).order_by("date")
        stats_map = {s.date: s for s in stats_qs}
        chart_labels = [d.strftime("%Y-%m-%d") for d in date_list]
        chart_inserted = [
            stats_map.get(d, None).total_inserted if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_skipped = [
            stats_map.get(d, None).total_skipped if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_ignored = [
            stats_map.get(d, None).total_ignored if stats_map.get(d, None) else 0
            for d in date_list
        ]
    else:
        chart_labels = []
        chart_inserted = []
        chart_skipped = []
        chart_ignored = []

    # Multi-line chart: daily totals for rejections, applications, interviews, total
    earliest_app = Application.objects.order_by("sent_date").first()
    # Default: use earliest application date
    app_start_date = earliest_app.sent_date if earliest_app else None
    # Check for REPORTING_DEFAULT_START_DATE in env
    env_start_date = os.environ.get("REPORTING_DEFAULT_START_DATE")
    reporting_default_start_date = None
    if env_start_date:
        try:
            # Accept YYYY-MM-DD only
            reporting_default_start_date = datetime.strptime(
                env_start_date.strip().replace('"', ""), "%Y-%m-%d"
            ).date()
        except Exception:
            reporting_default_start_date = None
    # Use the later of the two (env or earliest_app)
    if reporting_default_start_date and app_start_date:
        if reporting_default_start_date > app_start_date:
            app_start_date = reporting_default_start_date
    elif reporting_default_start_date:
        app_start_date = reporting_default_start_date

    # Load plot series config from JSON file and validate
    import json
    from .models import MessageLabel
    from django.core.exceptions import ValidationError
    import re

    def is_valid_color(color):
        # Accept #RRGGBB, #RGB, or valid CSS color names
        if re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", color):
            return True
        # Accept common color names (basic validation)
        css_colors = {
            "red",
            "blue",
            "green",
            "yellow",
            "gray",
            "grey",
            "black",
            "white",
            "orange",
            "purple",
            "pink",
            "brown",
            "teal",
            "lime",
            "indigo",
            "violet",
            "gold",
            "silver",
        }
        return color.lower() in css_colors

    plot_series_config = []
    try:
        with open("json/plot_series.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        allowed_labels = set(MessageLabel.objects.values_list("label", flat=True))
        for entry in config:
            label = entry.get("label")
            display_name = entry.get("display_name")
            color = entry.get("color")
            # Validate label
            if label not in allowed_labels:
                continue
            # Validate color
            if not is_valid_color(color):
                color = "#2563eb"  # fallback to default
            plot_series_config.append(
                {
                    "key": label,  # Add key field for chart logic
                    "label": label,
                    "display_name": display_name,
                    "color": color,
                    "ml_label": label,  # use label as ml_label for consistency
                }
            )
    except Exception as e:
        # fallback to hardcoded config if error
        plot_series_config = [
            {
                "label": "application",
                "display_name": "Application",
                "color": "#2563eb",
                "ml_label": "application",
            },
            {
                "label": "interview",
                "display_name": "Interview",
                "color": "#22c55e",
                "ml_label": "interview",
            },
            {
                "label": "rejected",
                "display_name": "Rejected",
                "color": "#ef4444",
                "ml_label": "rejected",
            },
            {
                "label": "ghosted",
                "display_name": "Ghosted",
                "color": "#a3a3a3",
                "ml_label": "ghosted",
            },
            {
                "label": "job_alert",
                "display_name": "Job Alert",
                "color": "#eab308",
                "ml_label": "job_alert",
            },
        ]

    # Now build date list
    if app_start_date:
        app_end_date = now().date()
        app_num_days = (app_end_date - app_start_date).days + 1
        app_date_list = [
            app_start_date + timedelta(days=i) for i in range(app_num_days)
        ]
        app_qs = Application.objects.filter(sent_date__gte=app_start_date)
    else:
        app_date_list = []
        app_qs = Application.objects.none()

    # Build chart data dynamically based on configured series
    chart_series_data = []
    msg_qs = (
        Message.objects.filter(timestamp__date__gte=app_start_date)
        if app_date_list
        else Message.objects.none()
    )

    for series in plot_series_config:
        ml_label = series["ml_label"]
        # Check if this is an application-based series or message-based series
        if ml_label == "job_application":
            # Applications per day
            apps_by_day = app_qs.values("sent_date").annotate(count=models.Count("id"))
            apps_map = {r["sent_date"]: r["count"] for r in apps_by_day}
            data = [apps_map.get(d, 0) for d in app_date_list]
        elif ml_label == "rejected":
            # Rejections per day
            rejs_by_day = (
                app_qs.exclude(rejection_date=None)
                .values("rejection_date")
                .annotate(count=models.Count("id"))
            )
            rejs_map = {r["rejection_date"]: r["count"] for r in rejs_by_day}
            data = [rejs_map.get(d, 0) for d in app_date_list]
        elif ml_label == "interview_invite":
            # Interviews per day
            ints_by_day = (
                app_qs.exclude(interview_date=None)
                .values("interview_date")
                .annotate(count=models.Count("id"))
            )
            ints_map = {r["interview_date"]: r["count"] for r in ints_by_day}
            data = [ints_map.get(d, 0) for d in app_date_list]
        else:
            # Message-based series (referral, head_hunter, noise, etc.)
            msgs_by_day = (
                msg_qs.filter(ml_label=ml_label)
                .extra(select={"day": "date(timestamp)"})
                .values("day")
                .annotate(count=models.Count("id"))
            )
            msgs_map = {r["day"]: r["count"] for r in msgs_by_day}
            data = [msgs_map.get(d.strftime("%Y-%m-%d"), 0) for d in app_date_list]

        chart_series_data.append(
            {
                "key": series["key"],
                "label": series["label"],
                "color": series["color"],
                "data": data,
            }
        )

    # Defensive: ensure all chart arrays exist
    chart_activity_labels = (
        [d.strftime("%Y-%m-%d") for d in app_date_list] if app_date_list else []
    )
    if not chart_labels:
        chart_labels = []
        chart_inserted = []
        chart_skipped = []
        chart_ignored = []
    if not chart_activity_labels:
        chart_activity_labels = []
        chart_series_data = []

    return render(
        request,
        "tracker/dashboard.html",
        {
            "companies": companies,
            "companies_list": companies_list,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "messages": messages,
            "threads": thread_list,
            "latest_stats": latest_stats,
            "chart_labels": chart_labels,
            "chart_inserted": chart_inserted,
            "chart_skipped": chart_skipped,
            "chart_ignored": chart_ignored,
            "chart_activity_labels": chart_activity_labels,
            "chart_series_data": chart_series_data,
            "plot_series_config": plot_series_config,
            "unresolved_companies": unresolved_companies,
            "ingested_today": ingested_today,
            "ignored_today": ignored_today,
            "skipped_today": skipped_today,
            "reporting_default_start_date": (
                reporting_default_start_date.strftime("%Y-%m-%d")
                if reporting_default_start_date
                else ""
            ),
        },
    )


def company_detail(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    applications = Application.objects.filter(company=company)
    messages = Message.objects.filter(company=company).order_by("timestamp")
    ctx = {"company": company, "applications": applications, "messages": messages}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/company_detail.html", ctx)


def extract_body_content(raw_html):
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script/style/noscript
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Extract body content if present
    body = soup.body
    return str(body) if body else soup.get_text(separator=" ", strip=True)


def label_applications(request):
    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith("label_") and value:
                app_id = int(key.split("_")[1])
                try:
                    app = Application.objects.get(pk=app_id)
                    app.ml_label = value
                    app.reviewed = True
                    app.save()
                except Message.DoesNotExist:
                    continue

        return redirect("label_applications")

    apps = Application.objects.filter(reviewed=False).order_by("sent_date")[:50]
    ctx = {"applications": apps}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/label_applications.html", ctx)


import json
import subprocess


@login_required
def label_messages(request):
    """Bulk message labeling interface with checkboxes"""
    training_output = None

    # Handle POST - Bulk label selected messages
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "bulk_label":
            selected_ids = request.POST.getlist("selected_messages")
            bulk_label = request.POST.get("bulk_label")

            if selected_ids and bulk_label:
                updated_count = 0
                touched_threads = set()
                for msg_id in selected_ids:
                    try:
                        msg = Message.objects.get(pk=msg_id)
                        msg.ml_label = bulk_label
                        msg.reviewed = True
                        msg.save()
                        if msg.thread_id:
                            touched_threads.add(msg.thread_id)
                        updated_count += 1
                    except Message.DoesNotExist:
                        continue

                # Also update corresponding Application rows by thread_id
                apps_updated = 0
                if touched_threads:
                    apps_updated = Application.objects.filter(
                        thread_id__in=list(touched_threads)
                    ).update(ml_label=bulk_label, reviewed=True)

                messages.success(
                    request,
                    f"✅ Labeled {updated_count} messages as '{bulk_label}'"
                    + (
                        f" and updated {apps_updated} application(s)"
                        if apps_updated
                        else ""
                    ),
                )

                # Check if we should retrain
                labeled_count = Message.objects.filter(reviewed=True).count()
                if labeled_count % 20 == 0:
                    messages.info(request, "🔄 Triggering model retraining...")
                    try:
                        subprocess.Popen([python_path, "train_model.py"])
                        messages.success(
                            request, "✅ Model retraining started in background"
                        )
                    except Exception as e:
                        messages.warning(request, f"⚠️ Could not start retraining: {e}")
            else:
                messages.warning(request, "⚠️ Please select messages and a label")

    # Get pagination parameters
    per_page = int(request.GET.get("per_page", 50))
    page = int(request.GET.get("page", 1))

    # Enhanced filtering
    filter_label = request.GET.get("label", "all")
    filter_confidence = request.GET.get("confidence", "all")  # low, medium, high, all
    filter_company = request.GET.get("company", "all")  # all, missing, resolved
    filter_reviewed = request.GET.get(
        "reviewed", "unreviewed"
    )  # unreviewed, reviewed, all
    sort = request.GET.get(
        "sort", ""
    )  # subject, company, confidence, sender_domain, date
    order = request.GET.get("order", "asc")  # asc, desc

    # Build queryset based on reviewed filter
    if filter_reviewed == "unreviewed":
        qs = Message.objects.filter(reviewed=False)
    elif filter_reviewed == "reviewed":
        qs = Message.objects.filter(reviewed=True)
    else:
        qs = Message.objects.all()

    # Apply label filter
    if filter_label and filter_label != "all":
        qs = qs.filter(ml_label=filter_label)

    # Apply confidence filter
    if filter_confidence == "low":
        qs = qs.filter(Q(confidence__lt=0.5) | Q(confidence__isnull=True))
    elif filter_confidence == "medium":
        qs = qs.filter(confidence__gte=0.5, confidence__lt=0.75)
    elif filter_confidence == "high":
        qs = qs.filter(confidence__gte=0.75)

    # Apply company filter
    if filter_company == "missing":
        qs = qs.filter(company__isnull=True)
    elif filter_company == "resolved":
        qs = qs.filter(company__isnull=False)

    # Do not exclude messages with blank or very short bodies; show all for debugging

    # Annotate helper fields for sorting
    qs = qs.select_related("company").annotate(
        company_name=Coalesce(F("company__name"), Value("")),
    )
    # Annotate sender_domain extracted after '@' when present
    at_pos = StrIndex(F("sender"), Value("@"))
    start_pos = ExpressionWrapper(at_pos + Value(1), output_field=IntegerField())
    sender_domain_expr = Case(
        When(sender__contains="@", then=Substr(F("sender"), start_pos)),
        default=F("sender"),
        output_field=CharField(),
    )
    qs = qs.annotate(sender_domain=sender_domain_expr)

    # Sorting
    sort = sort.lower()
    order = order.lower()
    is_desc = order == "desc"

    if sort == "confidence":
        qs = qs.order_by(
            (
                F("confidence").desc(nulls_last=True)
                if is_desc
                else F("confidence").asc(nulls_first=True)
            ),
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "company":
        qs = qs.order_by(
            "-company_name" if is_desc else "company_name",
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "sender_domain":
        qs = qs.order_by(
            "-sender_domain" if is_desc else "sender_domain",
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "subject":
        qs = qs.order_by(
            "-subject" if is_desc else "subject",
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "date":
        qs = qs.order_by("-timestamp" if is_desc else "timestamp")
    else:
        # Fallback: order by confidence priority similar to previous behavior
        if filter_confidence in ("high", "medium"):
            qs = qs.order_by(F("confidence").desc(nulls_last=True), "-timestamp")
        else:
            qs = qs.order_by(F("confidence").asc(nulls_first=True), "timestamp")

    # Pagination
    total_count = qs.count()
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    messages_page = qs[start_idx:end_idx]

    # Extract body snippets for display (plain text only)
    for msg in messages_page:
        if msg.body and msg.body.strip():
            soup = BeautifulSoup(msg.body, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            plain_text = soup.get_text(separator=" ", strip=True)
            plain_text = " ".join(plain_text.split())
            msg.body_snippet = plain_text[:200]
        else:
            msg.body_snippet = "[empty body]"

        if msg.subject and msg.subject.strip():
            msg.display_subject = msg.subject
        else:
            msg.display_subject = "[blank subject]"

        if msg.sender:
            sender_parts = msg.sender.split("@")
            msg.sender_domain = sender_parts[1] if len(sender_parts) > 1 else "unknown"
        else:
            msg.sender_domain = "unknown"

    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_previous = page > 1
    has_next = page < total_pages

    # Get stats
    total_unreviewed = Message.objects.filter(reviewed=False).count()
    total_reviewed = Message.objects.filter(reviewed=True).count()

    # Get distinct labels for filter (all labels, not just unreviewed)
    distinct_labels = (
        Message.objects.all().values_list("ml_label", flat=True).distinct()
    )

    # Available label choices
    label_choices = [
        "interview_invite",
        "job_application",
        "rejection",
        "offer",
        "noise",
        "job_alert",
        "head_hunter",
        "referral",
        "ghosted",
        "follow_up",
        "response",
        "other",
    ]

    # Get label distribution for prioritization
    label_counts = (
        Message.objects.filter(reviewed=True)
        .values("ml_label")
        .annotate(count=Count("ml_label"))
        .order_by("count")
    )

    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/label_messages.html",
        {
            "message_list": messages_page,
            "filter_label": filter_label,
            "filter_confidence": filter_confidence,
            "filter_company": filter_company,
            "sort": sort,
            "order": order,
            "distinct_labels": distinct_labels,
            "label_choices": label_choices,
            "label_counts": label_counts,
            "total_unreviewed": total_unreviewed,
            "total_reviewed": total_reviewed,
            "total_count": total_count,
            "per_page": per_page,
            "page": page,
            "total_pages": total_pages,
            "has_previous": has_previous,
            "has_next": has_next,
            "training_output": training_output,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "filter_reviewed": filter_reviewed,
        },
    )


@login_required
def metrics(request):
    metrics = {}
    training_output = None
    metrics_path = Path("model/model_info.json")
    if metrics_path.exists():
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        except Exception:
            metrics = {}
    # Optionally, show last training output
    output_path = Path("model/model_audit.json")
    if output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                audit = json.load(f)
                training_output = audit.get("training_output")
        except Exception:
            training_output = None

    # Ingestion stats plot data (same as dashboard)
    earliest_stat = IngestionStats.objects.order_by("date").first()
    if earliest_stat:
        start_date = earliest_stat.date
        end_date = now().date()
        num_days = (end_date - start_date).days + 1
        date_list = [start_date + timedelta(days=i) for i in range(num_days)]
        stats_qs = IngestionStats.objects.filter(date__gte=start_date).order_by("date")
        stats_map = {s.date: s for s in stats_qs}
        chart_labels = [d.strftime("%Y-%m-%d") for d in date_list]
        chart_inserted = [
            stats_map.get(d, None).total_inserted if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_skipped = [
            stats_map.get(d, None).total_skipped if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_ignored = [
            stats_map.get(d, None).total_ignored if stats_map.get(d, None) else 0
            for d in date_list
        ]
    else:
        chart_labels = []
        chart_inserted = []
        chart_skipped = []
        chart_ignored = []

    # Categorize labels into real vs extra (company names that need fixing)
    valid_labels = {
        "interview",
        "interview_invite",
        "application",
        "job_application",
        "rejected",
        "offer",
        "noise",
        "referral",
        "head_hunter",
        "job_alert",
        "ghosted",
        "follow_up",
        "response",
        "unknown",
    }
    label_breakdown = None
    if "labels" in metrics and isinstance(metrics["labels"], list):
        real_labels = [
            label for label in metrics["labels"] if label.lower() in valid_labels
        ]
        extra_labels = [
            label for label in metrics["labels"] if label.lower() not in valid_labels
        ]
        label_breakdown = {
            "real_count": len(real_labels),
            "extra_count": len(extra_labels),
            "real_labels": real_labels,
            "extra_labels": extra_labels,
        }

    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/metrics.html",
        {
            "metrics": metrics,
            "training_output": training_output,
            "label_breakdown": label_breakdown,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "chart_labels": chart_labels,
            "chart_inserted": chart_inserted,
            "chart_skipped": chart_skipped,
            "chart_ignored": chart_ignored,
        },
    )


@csrf_exempt
@login_required
def retrain_model(request):
    training_output = None
    if request.method == "POST":
        try:
            result = subprocess.run(
                [python_path, "train_model.py", "--verbose"],
                capture_output=True,
                text=True,
                check=True,
            )
            training_output = result.stdout
            # Optionally, save output to model/model_audit.json
            with open("model/model_audit.json", "w", encoding="utf-8") as f:
                json.dump({"training_output": training_output}, f)
        except subprocess.CalledProcessError as e:
            training_output = f"Retraining failed:\n{e.stderr}"
    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/metrics.html",
        {
            "metrics": {},
            "training_output": training_output,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        },
    )


import re
import html


def validate_regex_pattern(pattern):
    """
    Validate regex pattern for security issues.
    Returns (is_valid, error_message)
    """
    if not pattern or not isinstance(pattern, str):
        return False, "Pattern must be a non-empty string"

    # Length limit to prevent DoS
    if len(pattern) > 500:
        return False, "Pattern too long (max 500 characters)"

    # Check for suspicious patterns that could cause ReDoS
    # (Regular Expression Denial of Service)
    redos_patterns = [
        r"\(\?\#",  # Comment groups can be abused
        r"\(\?\=.*\)\+",  # Nested lookaheads with quantifiers
        r"\(\?\!.*\)\+",  # Nested negative lookaheads
        r"(\(.*\)\+){3,}",  # Multiple nested groups with quantifiers
    ]

    for redos in redos_patterns:
        if re.search(redos, pattern):
            return False, f"Pattern contains potentially unsafe construct"

    # Try to compile the regex to ensure it's valid
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex: {str(e)}"

    # Check for extremely complex patterns (complexity check)
    quantifier_count = len(re.findall(r"[*+?{]", pattern))
    if quantifier_count > 20:
        return False, "Pattern too complex (too many quantifiers)"

    return True, None


def sanitize_string(value, max_length=200, allow_regex=False):
    """
    Sanitize user input string for security.
    Returns sanitized string or None if invalid.
    """
    if not value or not isinstance(value, str):
        return None

    # Remove leading/trailing whitespace
    value = value.strip()

    if not value:
        return None

    # Length check
    if len(value) > max_length:
        return None

    # HTML escape to prevent XSS
    value = html.escape(value)

    # Block obvious code injection attempts
    dangerous_chars = [
        "<script",
        "javascript:",
        "onerror=",
        "onload=",
        "<?php",
        "<%",
        "__import__",
        "eval(",
        "exec(",
    ]
    value_lower = value.lower()
    for danger in dangerous_chars:
        if danger in value_lower:
            return None

    # Block path traversal
    if "../" in value or "..\\" in value or "%2e%2e" in value.lower():
        return None

    # Block null bytes
    if "\x00" in value:
        return None

    # For regex patterns, additional validation
    if allow_regex:
        is_valid, error = validate_regex_pattern(value)
        if not is_valid:
            return None

    return value


def validate_domain(domain):
    """
    Validate domain name format.
    Returns (is_valid, sanitized_domain)
    """
    if not domain or not isinstance(domain, str):
        return False, None

    domain = domain.strip().lower()

    # Length check
    if len(domain) > 253:
        return False, None

    # Basic domain format check
    # Allow letters, numbers, dots, hyphens
    if not re.match(
        r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
        domain,
    ):
        return False, None

    # Must have at least one dot (TLD)
    if "." not in domain:
        return False, None

    # HTML escape for safety
    domain = html.escape(domain)

    return True, domain


@login_required
def json_file_viewer(request):
    """View and edit JSON configuration files (patterns.json, companies.json)"""

    patterns_path = Path("json/patterns.json")
    companies_path = Path("json/companies.json")

    success_message = None
    error_message = None
    validation_errors = []

    # Handle POST - Save changes to JSON files
    if request.method == "POST":
        action = request.POST.get("action")
        file_type = request.POST.get("file_type")

        try:
            if action == "save_patterns":
                # Update patterns.json with security validation
                patterns_data = {}

                # Save message_labels patterns with validation
                for label in [
                    "interview",
                    "application",
                    "rejection",
                    "offer",
                    "noise",
                    "referral",
                    "head_hunter",
                    "job_alert",
                    "follow_up",
                    "response",
                    "ghosted",
                    "other",
                ]:
                    patterns_raw = (
                        request.POST.get(f"pattern_{label}", "").strip().split("\n")
                    )
                    patterns_list = []

                    for pattern in patterns_raw:
                        if not pattern.strip():
                            continue

                        # Validate and sanitize regex pattern
                        sanitized = sanitize_string(
                            pattern, max_length=500, allow_regex=True
                        )
                        if sanitized:
                            patterns_list.append(sanitized)
                        else:
                            validation_errors.append(
                                f"Invalid pattern in '{label}': {pattern[:50]}..."
                            )

                    if patterns_list:
                        if "message_labels" not in patterns_data:
                            patterns_data["message_labels"] = {}
                        patterns_data["message_labels"][label] = patterns_list

                # Save invalid_company_prefixes with validation
                invalid_prefixes_raw = (
                    request.POST.get("invalid_company_prefixes", "").strip().split("\n")
                )
                invalid_prefixes = []

                for prefix in invalid_prefixes_raw:
                    if not prefix.strip():
                        continue

                    # Validate prefix (alphanumeric + common chars only)
                    sanitized = sanitize_string(
                        prefix, max_length=100, allow_regex=False
                    )
                    if sanitized:
                        invalid_prefixes.append(sanitized)
                    else:
                        validation_errors.append(
                            f"Invalid company prefix: {prefix[:50]}..."
                        )

                if invalid_prefixes:
                    patterns_data["invalid_company_prefixes"] = invalid_prefixes

                # Save old-style patterns for backward compatibility
                for key in [
                    "application",
                    "rejection",
                    "interview",
                    "ignore",
                    "response",
                    "follow_up",
                ]:
                    old_patterns_raw = (
                        request.POST.get(f"old_{key}", "").strip().split("\n")
                    )
                    old_patterns = []

                    for pattern in old_patterns_raw:
                        if not pattern.strip():
                            continue

                        sanitized = sanitize_string(
                            pattern, max_length=500, allow_regex=False
                        )
                        if sanitized:
                            old_patterns.append(sanitized)

                    if old_patterns:
                        patterns_data[key] = old_patterns

                # Only write if no validation errors
                if validation_errors:
                    error_message = f"⚠️ Validation errors: {len(validation_errors)} patterns rejected for security reasons"
                else:
                    # Backup original file before overwriting
                    if patterns_path.exists():
                        backup_path = Path("json/patterns.json.backup")
                        import shutil

                        shutil.copy2(patterns_path, backup_path)

                    # Write to file with restrictive permissions
                    with open(patterns_path, "w", encoding="utf-8") as f:
                        json.dump(patterns_data, f, indent=2)

                    success_message = "✅ Patterns saved successfully! (Backup created)"

            elif action == "save_companies":
                # Update companies.json with security validation
                companies_data = {}

                # Save known companies with validation
                known_raw = request.POST.get("known_companies", "").strip().split("\n")
                known_list = []

                for company in known_raw:
                    if not company.strip():
                        continue

                    # Validate company name
                    sanitized = sanitize_string(
                        company, max_length=200, allow_regex=False
                    )
                    if sanitized:
                        known_list.append(sanitized)
                    else:
                        validation_errors.append(
                            f"Invalid company name: {company[:50]}..."
                        )

                if known_list:
                    companies_data["known"] = sorted(known_list)

                # Save domain mappings with validation
                domain_mappings = {}
                domains_raw = (
                    request.POST.get("domain_mappings", "").strip().split("\n")
                )

                for line in domains_raw:
                    if not line.strip():
                        continue

                    if ":" in line or "=" in line:
                        separator = ":" if ":" in line else "="
                        parts = line.split(separator, 1)

                        if len(parts) == 2:
                            domain = parts[0].strip()
                            company = parts[1].strip()

                            # Validate domain format
                            is_valid, sanitized_domain = validate_domain(domain)
                            if not is_valid:
                                validation_errors.append(
                                    f"Invalid domain format: {domain}"
                                )
                                continue

                            # Validate company name
                            sanitized_company = sanitize_string(
                                company, max_length=200, allow_regex=False
                            )
                            if not sanitized_company:
                                validation_errors.append(
                                    f"Invalid company name for domain {domain}"
                                )
                                continue

                            domain_mappings[sanitized_domain] = sanitized_company

                if domain_mappings:
                    companies_data["domain_to_company"] = domain_mappings

                # Save ATS domains with validation
                ats_raw = request.POST.get("ats_domains", "").strip().split("\n")
                ats_list = []

                for domain in ats_raw:
                    if not domain.strip():
                        continue

                    # Validate domain format
                    is_valid, sanitized_domain = validate_domain(domain)
                    if is_valid:
                        ats_list.append(sanitized_domain)
                    else:
                        validation_errors.append(f"Invalid ATS domain: {domain}")

                if ats_list:
                    companies_data["ats_domains"] = sorted(ats_list)

                # Save aliases with validation
                aliases = {}
                aliases_raw = request.POST.get("aliases", "").strip().split("\n")

                for line in aliases_raw:
                    if not line.strip():
                        continue

                    if ":" in line or "=" in line:
                        separator = ":" if ":" in line else "="
                        parts = line.split(separator, 1)

                        if len(parts) == 2:
                            alias = parts[0].strip()
                            canonical = parts[1].strip()

                            # Validate both alias and canonical names
                            sanitized_alias = sanitize_string(
                                alias, max_length=200, allow_regex=False
                            )
                            sanitized_canonical = sanitize_string(
                                canonical, max_length=200, allow_regex=False
                            )

                            if sanitized_alias and sanitized_canonical:
                                aliases[sanitized_alias] = sanitized_canonical
                            else:
                                validation_errors.append(
                                    f"Invalid alias: {alias} → {canonical}"
                                )

                if aliases:
                    companies_data["aliases"] = aliases

                # Check for reasonable data size (DoS prevention)
                total_entries = (
                    len(known_list)
                    + len(domain_mappings)
                    + len(ats_list)
                    + len(aliases)
                )

                if total_entries > 10000:
                    error_message = "❌ Too many entries (max 10,000 total). Possible DoS attempt blocked."
                elif validation_errors:
                    error_message = f"⚠️ Validation errors: {len(validation_errors)} entries rejected for security reasons"
                else:
                    # Backup original file before overwriting
                    if companies_path.exists():
                        backup_path = Path("json/companies.json.backup")
                        import shutil

                        shutil.copy2(companies_path, backup_path)

                    # Write to file
                    with open(companies_path, "w", encoding="utf-8") as f:
                        json.dump(companies_data, f, indent=2)

                    success_message = "✅ Companies configuration saved successfully! (Backup created)"

        except Exception as e:
            error_message = f"❌ Error saving file: {str(e)}"

    # Load current JSON data
    patterns_data = {}
    companies_data = {}

    try:
        if patterns_path.exists():
            with open(patterns_path, "r", encoding="utf-8") as f:
                patterns_data = json.load(f)
    except Exception as e:
        error_message = f"⚠️ Error loading patterns.json: {str(e)}"

    try:
        if companies_path.exists():
            with open(companies_path, "r", encoding="utf-8") as f:
                companies_data = json.load(f)
    except Exception as e:
        error_message = f"⚠️ Error loading companies.json: {str(e)}"

    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/json_file_viewer.html",
        {
            "patterns_data": patterns_data,
            "companies_data": companies_data,
            "success_message": success_message,
            "error_message": error_message,
            "validation_errors": validation_errors,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        },
    )
