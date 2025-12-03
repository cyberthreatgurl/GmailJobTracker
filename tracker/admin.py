from django.contrib import admin

from .models import (
    AppSetting,
    ATSDomain,
    Company,
    CompanyAlias,
    DomainToCompany,
    GmailFilterImportLog,
    KnownCompany,
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
    list_display = ("name", "domain")
    search_fields = ("name", "domain")


@admin.register(Message)
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
                    if new_label in ("job_application", "interview_invite") and obj.company:
                        try:
                            ThreadTracking.objects.create(
                                thread_id=obj.thread_id,
                                company=obj.company,
                                company_source=obj.company_source or "manual",
                                job_title="",
                                job_id="",
                                status="application",
                                sent_date=(obj.timestamp.date() if obj.timestamp else None),
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


custom_admin_site.register(ThreadTracking, ThreadTrackingAdmin)
custom_admin_site.register(Company, CompanyAdmin)
custom_admin_site.register(UnresolvedCompany, UnresolvedCompanyAdmin)
custom_admin_site.register(Ticket, TicketAdmin)
custom_admin_site.register(ModelTrainingRun)
custom_admin_site.register(ModelTrainingLabelMetric)
custom_admin_site.register(GmailFilterImportLog)

admin.site.register(KnownCompany)
admin.site.register(ATSDomain)
admin.site.register(DomainToCompany)
admin.site.register(CompanyAlias)
admin.site.register(MessageLabel)
admin.site.register(ModelTrainingRun)
admin.site.register(ModelTrainingLabelMetric)
admin.site.register(GmailFilterImportLog)
admin.site.register(AppSetting)
