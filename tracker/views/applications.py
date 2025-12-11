"""Applications views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now
from tracker.forms import ApplicationEditForm, ManualEntryForm
from tracker.models import Company, Message, ThreadTracking
from tracker.services import MessageService
from tracker.views.helpers import build_sidebar_context


def edit_application(request, pk):
    """Edit a single application (ThreadTracking) via a simple form."""
    app = get_object_or_404(ThreadTracking, pk=pk)
    if request.method == "POST":
        form = ApplicationEditForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect("flagged_applications")
    else:
        form = ApplicationEditForm(instance=app)
    return render(request, "tracker/edit.html", {"form": form})



def flagged_applications(request):
    """List applications that need attention (unresolved/low-confidence company attribution)."""
    flagged = ThreadTracking.objects.filter(
        models.Q(company="")
        | models.Q(company_source__in=["none", "ml_prediction", "sender_name_match"])
    ).order_by("-first_sent")[:100]

    return render(request, "tracker/flagged.html", {"applications": flagged})



@login_required
def manual_entry(request):
    """Manual entry form for job applications from external sources."""
    if request.method == "POST":
        form = ManualEntryForm(request.POST)
        if form.is_valid():
            # Extract cleaned data
            company_name = form.cleaned_data["company_name"]
            entry_type = form.cleaned_data["entry_type"]
            job_title = form.cleaned_data.get("job_title") or "Manual Entry"
            job_id = form.cleaned_data.get("job_id") or ""
            application_date = form.cleaned_data["application_date"]
            interview_date = form.cleaned_data.get("interview_date")
            notes = form.cleaned_data.get("notes") or ""
            source = form.cleaned_data.get("source") or "manual"

            # Get or create company
            # First try case-insensitive lookup
            existing_company = Company.objects.filter(name__iexact=company_name).first()

            if existing_company:
                company = existing_company
                # Update last contact and status
                company.last_contact = now()
                if entry_type == "rejection":
                    company.status = "rejected"
                elif entry_type == "interview" and company.status != "rejected":
                    company.status = "interview"
                company.save()
            else:
                # Create new company
                company = Company.objects.create(
                    name=company_name,
                    first_contact=now(),
                    last_contact=now(),
                    status=entry_type,
                )

            # Generate unique thread_id for manual entry
            import hashlib

            thread_id_base = f"manual_{company_name}_{job_title}_{application_date}_{now().timestamp()}"
            thread_id = hashlib.md5(thread_id_base.encode()).hexdigest()[:16]

            # Create Application record
            status_map = {
                "application": "application",
                "interview": "interview",
                "rejection": "rejected",
            }

            rejection_date = application_date if entry_type == "rejection" else None
            interview_dt = interview_date if entry_type == "interview" else None

            # Create application record (not used after creation, logged implicitly)
            ThreadTracking.objects.create(
                thread_id=thread_id,
                company=company,
                company_source="manual",
                job_title=job_title,
                job_id=job_id,
                status=status_map[entry_type],
                sent_date=application_date,
                rejection_date=rejection_date,
                interview_date=interview_dt,
                ml_label=entry_type,
                ml_confidence=1.0,  # Manual entries are 100% confident
                reviewed=True,
            )

            # Create Message record for tracking
            msg_id = f"manual_{thread_id}"
            subject = f"{entry_type.title()}: {job_title} at {company_name}"
            body = f"Source: {source}\n\n{notes}" if notes else f"Source: {source}"

            Message.objects.create(
                company=company,
                company_source="manual",
                sender=f"manual@{source}",
                subject=subject,
                body=body,
                body_html=f"<p>{body.replace(chr(10), '<br>')}</p>",
                timestamp=now(),
                msg_id=msg_id,
                thread_id=thread_id,
                ml_label=entry_type,
                confidence=1.0,
                reviewed=True,
            )

            messages.success(
                request,
                f"✅ Successfully added {entry_type} for {company_name} - {job_title}",
            )
            return redirect("manual_entry")
    else:
        form = ManualEntryForm()

    # Show recent manual entries
    recent_entries = (
        ThreadTracking.objects.filter(company_source="manual")
        .select_related("company")
        .order_by("-sent_date")[:20]
    )

    ctx = {
        "form": form,
        "recent_entries": recent_entries,
    }
    ctx.update(build_sidebar_context())
    return render(request, "tracker/manual_entry.html", ctx)



__all__ = ['edit_application', 'flagged_applications', 'manual_entry']
