# tracker/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from tracker.models import Company, Application, Message
from django.utils.timezone import now
from django.db import models
from django.db.models import F, Q
from datetime import timedelta
from collections import defaultdict
from tracker.forms import ApplicationEditForm

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
    companies_list = Company.objects.all()  # ← This is the definition

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
   
    # pull in recent messages
    messages = Message.objects.all().order_by('-timestamp')[:100]

    # ✅ Group messages by thread_id
    threads = defaultdict(list)
    for msg in Message.objects.all().order_by("thread_id", "timestamp"):
        threads[msg.thread_id].append(msg)

    # Convert to a list of (thread_id, [messages]) sorted by most recent message
    thread_list = sorted(
        threads.items(),
        key=lambda t: t[1][-1].timestamp,  # last message in thread
        reverse=True
    )[:50]  # limit to 50 threads
    
    return render(request, "tracker/dashboard.html", {
        "companies": companies,
        "companies_list": companies_list,
        "applications": applications,
        "rejections_week": rejections_week,
        "interviews_week": interviews_week,
        "upcoming_interviews": upcoming_interviews,
        "messages": messages, 
        "threads": thread_list,
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
        return redirect("label_messages")

    # ✅ Order by confidence ascending (NULLs first), then oldest first
    msgs = Message.objects.filter(reviewed=False).order_by(
        F("confidence").asc(nulls_first=True), "timestamp"
    )[:50]

    return render(request, "tracker/label_messages.html", {"messages": msgs})