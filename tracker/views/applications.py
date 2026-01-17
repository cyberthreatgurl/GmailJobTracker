"""Applications views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Q
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
    """Manual entry form for NEW job applications from external sources.
    
    Note: This form only creates new applications. To update milestones 
    (prescreen, interview, rejection, offer dates), use the Application Details
    section on the Label Companies page.
    """
    if request.method == "POST":
        form = ManualEntryForm(request.POST)
        if form.is_valid():
            # Extract cleaned data
            company_select = form.cleaned_data["company_select"]
            new_company_name = form.cleaned_data.get("new_company_name", "").strip()
            job_title = form.cleaned_data.get("job_title") or "Manual Entry"
            job_id = form.cleaned_data.get("job_id") or ""
            application_date = form.cleaned_data["application_date"]
            notes = form.cleaned_data.get("notes") or ""
            source = form.cleaned_data.get("source") or "manual"

            # Get or create company
            if company_select == "__new__":
                # Create new company (already validated in form.clean())
                company = Company.objects.create(
                    name=new_company_name,
                    first_contact=now(),
                    last_contact=now(),
                    status="new",  # New companies start with "new" status
                )
            else:
                # Get existing company by ID
                company = Company.objects.get(id=int(company_select))
                # Update last contact
                company.last_contact = now()
                # Update status to application if it's "new"
                if company.status == "new":
                    company.status = "application"
                company.save()

            # Generate unique thread_id for manual entry
            import hashlib

            thread_id_base = f"manual_{company.name}_{job_title}_{application_date}_{now().timestamp()}"
            thread_id = hashlib.md5(thread_id_base.encode()).hexdigest()[:16]

            # Create ThreadTracking record for the new application
            ThreadTracking.objects.create(
                thread_id=thread_id,
                company=company,
                company_source="manual",
                job_title=job_title,
                job_id=job_id,
                status="application",
                sent_date=application_date,
                ml_label="job_application",
                ml_confidence=1.0,  # Manual entries are 100% confident
                reviewed=True,
            )

            # Create Message record for tracking
            msg_id = f"manual_{thread_id}"
            subject = f"Application: {job_title} at {company.name}"
            body = f"Source: {source}\n\n{notes}" if notes else f"Source: {source}"

            # Convert application_date to timezone-aware datetime for timestamp field
            from datetime import datetime, time
            from django.utils import timezone
            naive_dt = datetime.combine(application_date, time(12, 0))
            app_datetime = timezone.make_aware(naive_dt)

            Message.objects.create(
                company=company,
                company_source="manual",
                sender=f"manual@{source}",
                subject=subject,
                body=body,
                body_html=f"<p>{body.replace(chr(10), '<br>')}</p>",
                timestamp=app_datetime,
                msg_id=msg_id,
                thread_id=thread_id,
                ml_label="job_application",
                confidence=1.0,
                reviewed=True,
            )

            messages.success(
                request,
                f"✅ Successfully added application for {company.name} - {job_title}",
            )
            return redirect("manual_entry")
    else:
        form = ManualEntryForm()

    # Show recent manual entries (includes new manual entries and updated existing entries)
    recent_entries = (
        ThreadTracking.objects.filter(
            company_source__in=["manual", "manual_update"]
        )
        .select_related("company")
        .order_by("-sent_date")[:20]
    )

    ctx = {
        "form": form,
        "recent_entries": recent_entries,
    }
    ctx.update(build_sidebar_context())
    return render(request, "tracker/manual_entry.html", ctx)


@login_required
def edit_manual_entry(request, thread_id):
    """Edit a manual application entry.
    
    Note: This only edits basic application info (company, job title, dates).
    Milestone dates (prescreen, interview, rejection, offer) should be updated
    via the Application Details section on the Label Companies page.
    """
    entry = get_object_or_404(ThreadTracking, thread_id=thread_id, company_source__in=["manual", "manual_update"])
    
    if request.method == "POST":
        form = ManualEntryForm(request.POST)
        if form.is_valid():
            # Extract cleaned data
            company_select = form.cleaned_data["company_select"]
            new_company_name = form.cleaned_data.get("new_company_name", "").strip()
            job_title = form.cleaned_data.get("job_title") or "Manual Entry"
            job_id = form.cleaned_data.get("job_id") or ""
            application_date = form.cleaned_data["application_date"]
            notes = form.cleaned_data.get("notes") or ""
            source = form.cleaned_data.get("source") or "manual"

            # Get or create company
            if company_select == "__new__":
                company = Company.objects.create(
                    name=new_company_name,
                    first_contact=now(),
                    last_contact=now(),
                    status="new",
                )
            else:
                company = Company.objects.get(id=int(company_select))
                company.last_contact = now()
                company.save()

            # Update ThreadTracking (preserve any existing milestone dates)
            entry.company = company
            entry.job_title = job_title
            entry.job_id = job_id
            entry.sent_date = application_date
            entry.save()

            # Update associated Message
            msg = Message.objects.filter(thread_id=thread_id).first()
            if msg:
                msg.company = company
                msg.subject = f"Application: {job_title} at {company.name}"
                msg.body = f"Source: {source}\n\n{notes}" if notes else f"Source: {source}"
                msg.body_html = f"<p>{msg.body.replace(chr(10), '<br>')}</p>"
                msg.save()

            messages.success(request, f"✅ Updated manual entry for {company.name}")
            return redirect("manual_entry")
    else:
        # Pre-populate form with existing data
        # Extract notes from Message body
        msg = Message.objects.filter(thread_id=thread_id).first()
        notes_text = ""
        source_text = "manual"
        if msg and msg.body:
            parts = msg.body.split("\n\n", 1)
            if parts[0].startswith("Source: "):
                source_text = parts[0].replace("Source: ", "").strip()
                notes_text = parts[1] if len(parts) > 1 else ""
        
        initial_data = {
            "company_select": str(entry.company.id),
            "job_title": entry.job_title,
            "job_id": entry.job_id,
            "application_date": entry.sent_date,
            "notes": notes_text,
            "source": source_text,
        }
        form = ManualEntryForm(initial=initial_data)

    ctx = {
        "form": form,
        "entry": entry,
        "is_edit": True,
    }
    ctx.update(build_sidebar_context())
    return render(request, "tracker/manual_entry.html", ctx)


@login_required
def delete_manual_entry(request, thread_id):
    """Delete a manual entry."""
    entry = get_object_or_404(ThreadTracking, thread_id=thread_id, company_source__in=["manual", "manual_update"])
    
    if request.method == "POST":
        company_name = entry.company.name
        job_title = entry.job_title
        
        # Delete associated Message
        Message.objects.filter(thread_id=thread_id).delete()
        
        # Delete ThreadTracking
        entry.delete()
        
        messages.success(request, f"🗑️ Deleted manual entry: {job_title} at {company_name}")
        return redirect("manual_entry")
    
    return redirect("manual_entry")


@login_required
def bulk_delete_manual_entries(request):
    """Delete multiple manual entries at once."""
    if request.method == "POST":
        thread_ids = request.POST.getlist("thread_ids")
        
        if not thread_ids:
            messages.warning(request, "No entries selected for deletion.")
            return redirect("manual_entry")
        
        # Get entries to delete
        entries = ThreadTracking.objects.filter(
            thread_id__in=thread_ids, 
            company_source="manual"
        )
        
        deleted_count = entries.count()
        
        if deleted_count == 0:
            messages.warning(request, "No valid entries found to delete.")
            return redirect("manual_entry")
        
        # Delete associated Messages
        Message.objects.filter(thread_id__in=thread_ids).delete()
        
        # Delete ThreadTracking entries
        entries.delete()
        
        messages.success(
            request, 
            f"🗑️ Successfully deleted {deleted_count} manual {'entry' if deleted_count == 1 else 'entries'}"
        )
        return redirect("manual_entry")
    
    return redirect("manual_entry")


@login_required
def get_company_job_titles(request, company_id):
    """API endpoint to get job titles for a company's existing applications."""
    from django.http import JsonResponse
    
    try:
        company = Company.objects.get(id=company_id)
        # Get distinct job titles from ThreadTracking for this company
        # Include entries that are applications (by status or ml_label)
        job_titles = (
            ThreadTracking.objects.filter(company=company)
            .filter(
                Q(status="application") | 
                Q(ml_label="job_application") |
                Q(ml_label="application")
            )
            .exclude(job_title__in=["", "Manual Entry"])
            .values_list("job_title", flat=True)
            .distinct()
            .order_by("job_title")
        )
        return JsonResponse({
            "success": True,
            "company_name": company.name,
            "job_titles": list(job_titles),
        })
    except Company.DoesNotExist:
        return JsonResponse({
            "success": False,
            "error": "Company not found",
            "job_titles": [],
        })


__all__ = ["edit_application", "flagged_applications", "manual_entry", "edit_manual_entry", "delete_manual_entry", "bulk_delete_manual_entries", "get_company_job_titles"]
