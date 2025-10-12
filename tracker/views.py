# tracker/views.py

import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from django.db import models
from django.db.models import F, Q
from tracker.models import Company, Application, Message, IngestionStats, UnresolvedCompany
from datetime import timedelta
from collections import defaultdict
from tracker.forms import ApplicationEditForm
from pathlib import Path
import subprocess

ALIAS_EXPORT_PATH = Path("alias_candidates.json")
PATTERNS_PATH = Path("patterns.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")

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
    if request.method == 'POST':
        form = ApplicationEditForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect('flagged_applications')
    else:
        form = ApplicationEditForm(instance=app)
    return render(request, 'tracker/edit.html', {'form': form})

def flagged_applications(request):
    flagged = Application.objects.filter(
        models.Q(company="") |
        models.Q(company_source__in=["none", "ml_prediction", "sender_name_match"])
    ).order_by('-first_sent')[:100]

    return render(request, 'tracker/flagged.html', {'applications': flagged})

@login_required
def dashboard(request):
    companies = Company.objects.count()
    companies_list = Company.objects.all()
    unresolved_companies = UnresolvedCompany.objects.filter(reviewed=False).order_by("-timestamp")[:50]
    
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by('interview_date')

    # ✅ Recent messages with company preloaded
    messages = Message.objects.select_related("company").order_by('-timestamp')[:100]

    # ✅ Group messages by thread_id with company preloaded
    threads = defaultdict(list)
    seen = set()

    for msg in Message.objects.select_related("company").order_by("thread_id", "timestamp"):
        if msg.msg_id not in seen:
            threads[msg.thread_id].append(msg)
            seen.add(msg.msg_id)

    # ✅ Filter to threads with >1 message, then sort and slice
    thread_list = sorted(
        [(tid, msgs) for tid, msgs in threads.items() if len(msgs) > 1],
        key=lambda t: t[1][-1].timestamp,
        reverse=True
    )[:50]

    # ✅ Ingestion stats
    latest_stats = IngestionStats.objects.order_by('-date').first()

    ingested_today = latest_stats.total_inserted if latest_stats else 0
    ignored_today = latest_stats.total_ignored if latest_stats else 0
    skipped_today = latest_stats.total_skipped if latest_stats else 0
    
    # Last 7 days for chart
    seven_days_ago = now().date() - timedelta(days=6)
    stats_qs = IngestionStats.objects.filter(date__gte=seven_days_ago).order_by("date")

    chart_labels = [s.date.strftime("%Y-%m-%d") for s in stats_qs]
    chart_inserted = [s.total_inserted for s in stats_qs]
    chart_skipped = [s.total_skipped for s in stats_qs]
    chart_ignored = [s.total_ignored for s in stats_qs]

    return render(request, "tracker/dashboard.html", {
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
        "unresolved_companies": unresolved_companies, 
        "ingested_today": ingested_today,
        "ignored_today": ignored_today,
        "skipped_today": skipped_today,
    })
  
    
def company_detail(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    applications = Application.objects.filter(company=company)
    messages = Message.objects.filter(company=company).order_by('timestamp')

    return render(request, "tracker/company_detail.html", {
        "company": company,
        "applications": applications,
        "messages": messages,
    })

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

@login_required
def label_messages(request):
    training_output = None  # ✅ Initialize outside POST block

    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith("label_") and value:
                msg_id = int(key.split("_")[1])
                try:
                    msg = Message.objects.get(pk=msg_id)
                    msg.ml_label = value
                    msg.reviewed = True
                    msg.save()
                except Message.DoesNotExist:
                    continue

        # ✅ Trigger model retraining and capture output
        try:
            result = subprocess.run(
                ["python", "train_model.py"],
                capture_output=True,
                text=True,
                check=True
            )
            training_output = result.stdout
            print("✅ Model retrained successfully.")
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            training_output = f"❌ Model retraining failed:\n{e.stderr}"
            print(training_output)

    # ✅ Continue rendering page with training_output in context
    filter_label = request.GET.get("label")
    qs = Message.objects.filter(reviewed=False)
    if filter_label:
        qs = qs.filter(ml_label=filter_label)

    msgs = qs.order_by(F("confidence").asc(nulls_first=True), "timestamp")[:50]

    total_unreviewed = Message.objects.filter(reviewed=False).count()
    total_reviewed = Message.objects.filter(reviewed=True).count()

    return render(request, "tracker/label_messages.html", {
        "messages": msgs,
        "filter_label": filter_label,
        "total_unreviewed": total_unreviewed,
        "total_reviewed": total_reviewed,
        "training_output": training_output  # ✅ Pass to template
    })