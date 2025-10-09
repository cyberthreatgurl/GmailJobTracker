from django.contrib import admin
from .models import Company, Application, Message, UnresolvedCompany



class UnresolvedCompanyAdmin(admin.ModelAdmin):
    fields = ("msg_id", "subject", "body", "sender", "sender_domain", "timestamp", "notes", "reviewed")
    
    list_display = ("msg_id", "sender_domain", "timestamp", "reviewed")
    list_filter = ("reviewed", "sender_domain")
    search_fields = ("msg_id", "subject", "body", "sender", "sender_domain")
    readonly_fields = ("msg_id", "subject", "body", "sender", "sender_domain", "timestamp")
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
        context['message_count'] = Message.objects.count()
        return context

custom_admin_site = CustomAdminSite(name='custom_admin')

def mark_as_reviewed(modeladmin, request, queryset):
    queryset.update(reviewed=True)
mark_as_reviewed.short_description = "Mark selected applications as reviewed"

class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("job_title", "company", "ml_label", "ml_confidence", "reviewed", "sent_date")
    list_filter = ("ml_label", "reviewed", "company_source")
    search_fields = ("job_title", "company__name", "thread_id", "ml_label")
    actions = [mark_as_reviewed]

class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "domain")
    search_fields = ("name", "domain")

class MessageAdmin(admin.ModelAdmin):
    list_display = ("thread_id", "timestamp", "sender", "subject")
    search_fields = ("subject", "sender", "body")

custom_admin_site.register(Application, ApplicationAdmin)
custom_admin_site.register(Company, CompanyAdmin)
custom_admin_site.register(Message, MessageAdmin)
custom_admin_site.register(UnresolvedCompany, UnresolvedCompanyAdmin)