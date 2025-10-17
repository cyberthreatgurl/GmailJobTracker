from django.contrib.auth.decorators import login_required
from django.contrib import messages


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
        "tracker/delete_company.html",
        {
            "company": company,
            "companies": companies_count,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        },
    )


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
            if request.method == "POST":
                form = CompanyEditForm(request.POST, instance=selected_company)
                if form.is_valid():
                    form.save()
            else:
                form = CompanyEditForm(instance=selected_company)

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
        "tracker/label_companies.html",
        {
            "companies": companies_count,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "company_list": companies,
            "selected_company": selected_company,
            "form": form,
            "latest_label": latest_label,
        },
    )


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
from django.db import models
from django.db.models import F, Q, Count
from bs4 import BeautifulSoup

python_path = sys.executable
ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")


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
        return render(request, "tracker/manage_aliases.html", {"suggestions": []})

    with open(ALIAS_EXPORT_PATH, "r", encoding="utf-8") as f:
        suggestions = json.load(f)

    return render(request, "tracker/manage_aliases.html", {"suggestions": suggestions})


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

    # Last 30 days for chart
    days_back = 30
    start_date = now().date() - timedelta(days=days_back - 1)
    date_list = [start_date + timedelta(days=i) for i in range(days_back)]

    # Ingestion stats (existing)
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

    # Multi-line chart: daily totals for rejections, applications, interviews, total
    app_qs = Application.objects.filter(sent_date__gte=start_date)

    # Build date→count dicts for each type
    def date_count(qs, field):
        return {
            r["date"]: r["count"]
            for r in qs.values(field)
            .annotate(date=models.F(field))
            .values("date")
            .annotate(count=models.Count("id"))
        }

    # Applications per day
    apps_by_day = app_qs.values("sent_date").annotate(count=models.Count("id"))
    apps_map = {r["sent_date"]: r["count"] for r in apps_by_day}
    # Rejections per day
    rejs_by_day = (
        app_qs.exclude(rejection_date=None)
        .values("rejection_date")
        .annotate(count=models.Count("id"))
    )
    rejs_map = {r["rejection_date"]: r["count"] for r in rejs_by_day}
    # Interviews per day
    ints_by_day = (
        app_qs.exclude(interview_date=None)
        .values("interview_date")
        .annotate(count=models.Count("id"))
    )
    ints_map = {r["interview_date"]: r["count"] for r in ints_by_day}

    # Message counts by label per day
    msg_qs = Message.objects.filter(timestamp__date__gte=start_date)
    # Referrals per day
    refs_by_day = (
        msg_qs.filter(ml_label="referral")
        .extra(select={"day": "date(timestamp)"})
        .values("day")
        .annotate(count=models.Count("id"))
    )
    refs_map = {r["day"]: r["count"] for r in refs_by_day}
    # Head hunter messages per day
    hh_by_day = (
        msg_qs.filter(ml_label="head_hunter")
        .extra(select={"day": "date(timestamp)"})
        .values("day")
        .annotate(count=models.Count("id"))
    )
    hh_map = {r["day"]: r["count"] for r in hh_by_day}

    # Cumulative total applications
    total = 0
    total_apps = []
    for d in date_list:
        total += apps_map.get(d, 0)
        total_apps.append(total)

    chart_rejections = [rejs_map.get(d, 0) for d in date_list]
    chart_applications = [apps_map.get(d, 0) for d in date_list]
    chart_interviews = [ints_map.get(d, 0) for d in date_list]
    chart_referrals = [refs_map.get(d, 0) for d in date_list]
    chart_headhunters = [hh_map.get(d, 0) for d in date_list]
    chart_total = total_apps

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
            "chart_rejections": chart_rejections,
            "chart_applications": chart_applications,
            "chart_interviews": chart_interviews,
            "chart_referrals": chart_referrals,
            "chart_headhunters": chart_headhunters,
            "chart_total": chart_total,
            "unresolved_companies": unresolved_companies,
            "ingested_today": ingested_today,
            "ignored_today": ignored_today,
            "skipped_today": skipped_today,
        },
    )


def company_detail(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    applications = Application.objects.filter(company=company)
    messages = Message.objects.filter(company=company).order_by("timestamp")

    # Sidebar context
    companies = Company.objects.count()
    total_applications = Application.objects.count()
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
        "tracker/company_detail.html",
        {
            "company": company,
            "applications": applications,
            "messages": messages,
            "companies": companies,
            "applications_count": total_applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        },
    )


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
    return render(request, "tracker/label_applications.html", {"applications": apps})


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
                for msg_id in selected_ids:
                    try:
                        msg = Message.objects.get(pk=msg_id)
                        msg.ml_label = bulk_label
                        msg.reviewed = True
                        msg.save()
                        updated_count += 1
                    except Message.DoesNotExist:
                        continue

                messages.success(
                    request, f"✅ Labeled {updated_count} messages as '{bulk_label}'"
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

    # ✅ Enhanced filtering
    filter_label = request.GET.get("label", "all")
    filter_confidence = request.GET.get("confidence", "low")  # low, medium, high, all
    filter_company = request.GET.get("company", "all")  # all, missing, resolved

    qs = Message.objects.filter(reviewed=False)

    # Apply label filter
    if filter_label and filter_label != "all":
        qs = qs.filter(ml_label=filter_label)

    # Apply confidence filter
    if filter_confidence == "low":
        qs = qs.filter(confidence__lt=0.5) | qs.filter(confidence__isnull=True)
    elif filter_confidence == "medium":
        qs = qs.filter(confidence__gte=0.5, confidence__lt=0.75)
    elif filter_confidence == "high":
        qs = qs.filter(confidence__gte=0.75)

    # Apply company filter
    if filter_company == "missing":
        qs = qs.filter(company__isnull=True)
    elif filter_company == "resolved":
        qs = qs.filter(company__isnull=False)

    # Filter out messages with blank or very short bodies
    qs = qs.exclude(body__isnull=True).exclude(body="").exclude(body__regex=r"^\s*$")

    # Order by priority: low confidence first, then timestamp
    qs = qs.order_by(F("confidence").asc(nulls_first=True), "timestamp")

    # Pagination
    total_count = qs.count()
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    messages_page = qs[start_idx:end_idx]

    # Extract body snippets for display (plain text only)
    for msg in messages_page:
        if msg.body:
            # Parse HTML and extract plain text
            soup = BeautifulSoup(msg.body, "html.parser")
            # Remove script/style/noscript tags
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            # Get plain text, collapse whitespace
            plain_text = soup.get_text(separator=" ", strip=True)
            # Collapse multiple spaces
            plain_text = " ".join(plain_text.split())
            msg.body_snippet = plain_text[:200]
        else:
            msg.body_snippet = ""

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

    # Get distinct labels for filter
    distinct_labels = (
        Message.objects.filter(reviewed=False)
        .values_list("ml_label", flat=True)
        .distinct()
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

    # Categorize labels into real vs extra (company names that need fixing)
    valid_labels = {
        "interview",
        "interview_invite",
        "application",
        "job_application",
        "rejection",
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
