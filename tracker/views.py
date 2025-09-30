# tracker/views.py

from django.shortcuts import render, redirect, get_object_or_404
from tracker.models import Company, Application, Message
from django.utils.timezone import now
from django.db import models
from django.db.models import Q
from datetime import timedelta

from django.shortcuts import render, redirect
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

    return render(request, "tracker/dashboard.html", {
        "companies": companies,
        "companies_list": companies_list,
        "applications": applications,
        "rejections_week": rejections_week,
        "interviews_week": interviews_week,
        "upcoming_interviews": upcoming_interviews,
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
                app = Application.objects.get(pk=app_id)
                app.ml_label = value
                app.reviewed = True
                app.save()
        return redirect("label_applications")

    apps = Application.objects.filter(reviewed=False).order_by("sent_date")[:50]
    return render(request, "tracker/label_applications.html", {"applications": apps})