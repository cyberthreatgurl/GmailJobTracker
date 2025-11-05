from django.contrib import admin
from .models import (
    Company,
    ThreadTracking,
    Message,
    UnresolvedCompany,
    KnownCompany,
    ATSDomain,
    DomainToCompany,
    CompanyAlias,
    Ticket,
    MessageLabel,
    ModelTrainingRun,
    ModelTrainingLabelMetric,
    GmailFilterImportLog,
    AppSetting,
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
    )
    list_filter = ("ml_label", "reviewed", "company_source")
    search_fields = ("job_title", "company__name", "thread_id", "ml_label")
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
