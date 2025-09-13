from django.shortcuts import render, get_object_or_404
from .models import Company, Application, Message
from django.utils.timezone import now
from datetime import timedelta

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
