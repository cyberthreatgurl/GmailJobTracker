from django import forms
from django.contrib import admin
from django.shortcuts import render, redirect
from django.urls import path
from django.contrib import messages

from .models import (
    AppSetting,
    ATSDomain,
    Company,
    CompanyAlias,
    DomainToCompany,
    GmailFilterImportLog,
    KnownCompany,
    AuditEvent,
    Message,
    MessageLabel,
    ModelTrainingLabelMetric,
    ModelTrainingRun,
    ThreadTracking,
    Ticket,
    UnresolvedCompany,
)

list_display = ("name", "message_count", "application_count")


class UnresolvedCompanyAdmin(admin.ModelAdmin):
    fields = (
        "msg_id",
        "subject",
        "body",
        "sender",
        "sender_domain",
        "timestamp",
        "notes",
        "reviewed",
    )

    list_display = ("msg_id", "sender_domain", "timestamp", "reviewed")
    list_filter = ("reviewed", "sender_domain")
    search_fields = ("msg_id", "subject", "body", "sender", "sender_domain")
    readonly_fields = (
        "msg_id",
        "subject",
        "body",
        "sender",
        "sender_domain",
        "timestamp",
    )
    actions = ["mark_as_reviewed"]

    def mark_as_reviewed(self, request, queryset):
        updated = queryset.update(reviewed=True)
        self.message_user(request, f"{updated} entries marked as reviewed.")

    mark_as_reviewed.short_description = "Mark selected as reviewed"


class CustomAdminSite(admin.AdminSite):
    site_header = "Gmail Job Tracker Admin"
    site_title = "Gmail Job Tracker"
    index_title = "Dashboard"

    def each_context(self, request):
        context = super().each_context(request)
        context["message_count"] = Message.objects.count()
        return context


custom_admin_site = CustomAdminSite(name="custom_admin")


def mark_as_reviewed(modeladmin, request, queryset):
    queryset.update(reviewed=True)


mark_as_reviewed.short_description = "Mark selected applications as reviewed"


class ThreadTrackingAdmin(admin.ModelAdmin):
    list_display = (
        "job_title",
        "company",
        "ml_label",
        "ml_confidence",
        "reviewed",
        "sent_date",
        "interview_date",
        "interview_completed",
    )
    list_filter = ("ml_label", "reviewed", "company_source", "interview_completed")
    search_fields = ("job_title", "company__name", "thread_id", "ml_label")
    list_editable = ("interview_completed",)
    actions = [mark_as_reviewed]


class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "status", "first_contact", "last_contact")
    search_fields = ("name", "domain", "alias")
    list_filter = ("status",)
    actions = ["merge_selected_companies"]

    def merge_selected_companies(self, request, queryset):
        """Admin action to merge selected companies."""
        from django.shortcuts import redirect
        selected = queryset.values_list("id", flat=True)
        if len(selected) < 2:
            self.message_user(
                request,
                "⚠️ Please select at least 2 companies to merge.",
                level="warning"
            )
            return
        
        # Redirect to merge view with selected company IDs
        company_ids = "&".join([f"company_ids={cid}" for cid in selected])
        return redirect(f"/merge-companies/?{company_ids}")
    
    merge_selected_companies.short_description = "🔗 Merge selected companies"


class EMLUploadForm(forms.Form):
    """Form for uploading .eml files to ingest into the database."""

    eml_file = forms.FileField(
        label="Select .eml file",
        help_text="Upload an email message in .eml format to ingest into the tracker",
        widget=forms.FileInput(attrs={"accept": ".eml"}),
    )


class MessageAdmin(admin.ModelAdmin):
    list_display = [
        "timestamp",
        "company",
        "subject",
        "ml_label",  # Add this
        "confidence",
        "reviewed",
    ]
    list_filter = [
        "ml_label",  # Add this
        "reviewed",
        "company",
        "timestamp",
    ]
    search_fields = ["subject", "sender", "body"]
    readonly_fields = ["msg_id", "thread_id", "timestamp", "sender"]

    def get_urls(self):
        """Add custom URL for .eml file upload."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "upload-eml/",
                self.admin_site.admin_view(self.upload_eml_view),
                name="tracker_message_upload_eml",
            ),
        ]
        return custom_urls + urls

    def upload_eml_view(self, request):
        """View to handle .eml file upload and ingestion."""
        if request.method == "POST":
            form = EMLUploadForm(request.POST, request.FILES)
            if form.is_valid():
                eml_file = request.FILES["eml_file"]
                try:
                    # Read the .eml file content
                    eml_content = eml_file.read().decode("utf-8", errors="ignore")

                    # Import the ingestion function
                    from parser import ingest_message_from_eml

                    # Ingest the message
                    result = ingest_message_from_eml(eml_content)

                    if result == "inserted":
                        messages.success(
                            request,
                            f"Successfully ingested email from file: {eml_file.name}",
                        )
                    elif result == "skipped":
                        messages.warning(
                            request,
                            f"Email already exists in database: {eml_file.name}",
                        )
                    elif result == "ignored":
                        messages.info(
                            request,
                            f"Email was ignored (blank body or newsletter): {eml_file.name}",
                        )
                    else:
                        messages.error(
                            request,
                            f"Failed to ingest email from file: {eml_file.name}",
                        )

                    return redirect("..")
                except Exception as e:
                    messages.error(request, f"Error processing .eml file: {str(e)}")
        else:
            form = EMLUploadForm()

        context = {
            "form": form,
            "title": "Upload .eml File",
            "site_title": self.admin_site.site_title,
            "site_header": self.admin_site.site_header,
            "has_permission": True,
        }
        return render(request, "admin/message_upload_eml.html", context)

    def save_model(self, request, obj, form, change):
        """When a Message's ml_label is changed manually in admin, keep ThreadTracking in sync.

        - If label becomes an application/interview and a ThreadTracking doesn't exist, create one (only when company present).
        - If ThreadTracking exists, update its ml_label and ml_confidence to reflect the manual change.
        """
        old_label = None
        try:
            if change and obj.pk:
                old = Message.objects.get(pk=obj.pk)
                old_label = old.ml_label
        except Message.DoesNotExist:
            old_label = None

        super().save_model(request, obj, form, change)

        # If label changed, propagate to ThreadTracking
        try:
            new_label = obj.ml_label
            if old_label != new_label and obj.thread_id:
                tt = ThreadTracking.objects.filter(thread_id=obj.thread_id).first()
                if tt:
                    tt.ml_label = new_label
                    tt.ml_confidence = obj.confidence or tt.ml_confidence
                    tt.save()
                else:
                    # Create ThreadTracking for application-like labels when company is available
                    if (
                        new_label in ("job_application", "interview_invite")
                        and obj.company
                    ):
                        try:
                            ThreadTracking.objects.create(
                                thread_id=obj.thread_id,
                                company=obj.company,
                                company_source=obj.company_source or "manual",
                                job_title="",
                                job_id="",
                                status="application",
                                sent_date=(
                                    obj.timestamp.date() if obj.timestamp else None
                                ),
                                ml_label=new_label,
                                ml_confidence=(obj.confidence or 0.0),
                            )
                        except Exception:
                            # Soft-fail; admin save should not error due to ThreadTracking creation issues
                            pass
        except Exception:
            # Never crash admin save due to propagation errors
            pass


class TicketAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "updated_at")
    list_filter = ("category", "status")
    search_fields = ("title", "description")


custom_admin_site.register(Message, MessageAdmin)
custom_admin_site.register(ThreadTracking, ThreadTrackingAdmin)
custom_admin_site.register(Company, CompanyAdmin)
custom_admin_site.register(UnresolvedCompany, UnresolvedCompanyAdmin)
custom_admin_site.register(Ticket, TicketAdmin)
custom_admin_site.register(ModelTrainingRun)
custom_admin_site.register(ModelTrainingLabelMetric)
custom_admin_site.register(GmailFilterImportLog)


class AuditEventAdmin(admin.ModelAdmin):
    """Read-only admin for AuditEvent rows."""

    list_display = (
        "created_at",
        "action",
        "user",
        "msg_id",
        "db_id",
        "thread_id",
        "company_id",
        "pid",
    )
    search_fields = ("action", "user", "msg_id", "thread_id")
    list_filter = ("action", "user")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


custom_admin_site.register(AuditEvent, AuditEventAdmin)
admin.site.register(AuditEvent, AuditEventAdmin)

admin.site.register(KnownCompany)
admin.site.register(ATSDomain)
admin.site.register(DomainToCompany)
admin.site.register(CompanyAlias)
admin.site.register(MessageLabel)
admin.site.register(ModelTrainingRun)
admin.site.register(ModelTrainingLabelMetric)
admin.site.register(GmailFilterImportLog)
admin.site.register(AppSetting)
