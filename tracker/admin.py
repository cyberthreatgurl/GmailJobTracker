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
    CompanyNews,
    DefenseContract,
    DomainToCompany,
    GmailFilterImportLog,
    KnownCompany,
    AuditEvent,
    Message,
    MessageLabel,
    ModelTrainingLabelMetric,
    ModelTrainingRun,
    SamGovOpportunity,
    ScrapedArticle,
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
        from django.urls import reverse
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
        return redirect(f"{reverse('merge_companies')}?{company_ids}")
    
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


class DefenseContractAdmin(admin.ModelAdmin):
    """Admin for DefenseContract records with dual-source support (DoD + USASpending)."""

    list_display = (
        "company_name_raw",
        "data_source_badge",
        "branch_or_agency",
        "amount_display",
        "article_date",
        "company_location",
        "company_linked",
        "is_modification",
        "is_small_business",
    )
    list_filter = (
        "data_source",
        "branch",
        "awarding_agency",
        "is_modification",
        "is_small_business",
        "article_date",
    )
    search_fields = (
        "company_name_raw",
        "description",
        "contract_number",
        "award_id",
        "work_location",
        "contracting_activity",
        "awarding_agency",
        "awarding_sub_agency",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "data_source",
        "award_id",
        "company_link_display",
    )
    ordering = ("-article_date",)
    actions = ["unlink_company"]

    fieldsets = (
        ("Company Information", {
            "fields": (
                "company_name_raw",
                "company",
                "company_link_display",
                "company_location",
            )
        }),
        ("Contract Details", {
            "fields": (
                "data_source",
                "award_id",
                "contract_number",
                "amount",
                "description",
                "raw_text",
            )
        }),
        ("Source-Specific Fields", {
            "fields": (
                "branch",
                "awarding_agency",
                "awarding_sub_agency",
            ),
            "description": "Branch applies to DoD contracts, agencies to USASpending contracts"
        }),
        ("Location & Completion", {
            "fields": (
                "work_location",
                "place_of_performance_state",
                "completion_date",
                "contracting_activity",
            )
        }),
        ("Metadata", {
            "fields": (
                "article_date",
                "source_url",
                "is_modification",
                "is_small_business",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",)
        }),
    )

    def data_source_badge(self, obj):
        """Display data source with color coding."""
        if obj.data_source == "war_gov":
            return "🏛️ DoD"
        elif obj.data_source == "usaspending":
            return "🏢 Federal"
        return obj.data_source
    data_source_badge.short_description = "Source"

    def branch_or_agency(self, obj):
        """Display branch for DoD or agency for USASpending."""
        if obj.data_source == "war_gov" and obj.branch:
            return obj.get_branch_display()
        elif obj.data_source == "usaspending" and obj.awarding_agency:
            return obj.awarding_agency[:30] + "..." if len(obj.awarding_agency) > 30 else obj.awarding_agency
        return "-"
    branch_or_agency.short_description = "Branch/Agency"

    def company_linked(self, obj):
        """Display whether contract is linked to a Company record."""
        if obj.company:
            return f"✅ {obj.company.name}"
        return "❌ Unlinked"
    company_linked.short_description = "Company Link"

    def company_link_display(self, obj):
        """Display detailed company link information with unlink button."""
        if not obj.company:
            return "No company linked"
        
        from django.utils.html import format_html
        from django.urls import reverse
        
        company_url = reverse("admin:tracker_company_change", args=[obj.company.id])
        return format_html(
            '<div style="padding: 10px; background: #e8f5e9; border-left: 4px solid #4caf50;">'
            '<strong>Linked Company:</strong> <a href="{}" target="_blank">{}</a><br>'
            '<strong>Match Type:</strong> {}<br>'
            '<strong>Domain:</strong> {}<br>'
            '<em>Use "Unlink company" action below to remove this association</em>'
            '</div>',
            company_url,
            obj.company.name,
            "Fuzzy Match (85%+)" if obj.company else "Exact Match",
            obj.company.domain or "N/A",
        )
    company_link_display.short_description = "Company Association"

    def unlink_company(self, request, queryset):
        """Admin action to unlink company from selected contracts."""
        updated = queryset.filter(company__isnull=False).update(company=None)
        if updated:
            messages.success(
                request,
                f"✅ Successfully unlinked {updated} contract(s) from their companies. "
                f"You can re-run company matching to link them again."
            )
        else:
            messages.warning(
                request,
                "⚠️ No contracts were updated. Selected contracts may already be unlinked."
            )
    unlink_company.short_description = "🔗 Unlink company from selected contracts"


custom_admin_site.register(DefenseContract, DefenseContractAdmin)


class ScrapedArticleAdmin(admin.ModelAdmin):
    """Admin for ScrapedArticle cache records."""

    list_display = (
        "title",
        "article_date",
        "contracts_found",
        "scraped_at",
    )
    list_filter = ("article_date",)
    search_fields = ("title", "url")
    readonly_fields = ("scraped_at",)
    ordering = ("-article_date",)


custom_admin_site.register(ScrapedArticle, ScrapedArticleAdmin)


class CompanyNewsAdmin(admin.ModelAdmin):
    """Admin interface for company news caching."""

    readonly_fields = (
        'company',
        'last_fetched',
        'created_at',
        'updated_at',
        'articles_display',
        'all_articles_display'
    )
    list_display = ('company', 'article_count', 'last_fetched', 'is_fresh')
    list_filter = ('last_fetched', 'created_at')
    search_fields = ('company__name',)
    fieldsets = (
        ('Company', {
            'fields': ('company',)
        }),
        ('Cache Status', {
            'fields': (
                'last_fetched',
                'cache_duration_hours',
                'is_fresh'
            ),
            'classes': ('collapse',)
        }),
        ('Error Tracking', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Articles', {
            'fields': ('articles_display', 'all_articles_display'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def article_count(self, obj) -> int:
        """Display count of current cached articles."""
        return len(obj.articles) if obj.articles else 0

    article_count.short_description = 'Articles'

    def is_fresh(self, obj) -> str:
        """Show if cache is fresh."""
        if obj.is_cache_fresh():
            return '✅ Fresh'
        return '⚠️ Stale'

    is_fresh.short_description = 'Cache Status'

    def articles_display(self, obj) -> str:
        """Display current cached articles."""
        if not obj.articles:
            return 'No cached articles'
        lines = []
        for article in obj.get_display_articles():
            lines.append(
                f"• {article['title']}<br/>"
                f"  <a href='{article['url']}' target='_blank'>Read</a> "
                f"({article['date']})"
            )
        return '<br/>'.join(lines)

    articles_display.short_description = 'Display Articles'

    def all_articles_display(self, obj) -> str:
        """Display historical articles summary."""
        all_articles = obj.get_all_articles()
        if not all_articles:
            return 'No historical data'
        return f'{len(all_articles)} total articles in history'

    all_articles_display.short_description = 'Historical Record'


admin.site.register(CompanyNews, CompanyNewsAdmin)

admin.site.register(KnownCompany)
admin.site.register(ATSDomain)
admin.site.register(DomainToCompany)
admin.site.register(CompanyAlias)
admin.site.register(MessageLabel)
admin.site.register(ModelTrainingRun)
admin.site.register(ModelTrainingLabelMetric)
admin.site.register(GmailFilterImportLog)
admin.site.register(AppSetting)

class SamGovOpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "solicitation_number", "posted_date", "type", "fetched_at")
    list_filter = ("type", "posted_date")
    search_fields = ("title", "solicitation_number", "description")
    ordering = ("-posted_date",)
    readonly_fields = ("fetched_at",)

custom_admin_site.register(SamGovOpportunity, SamGovOpportunityAdmin)

from tracker.models import ContractIgnoreRule

from django import forms
from tracker.models import DefenseContract, NAICSCode
from django.db.models import Exists, OuterRef

class ContractIgnoreRuleForm(forms.ModelForm):
    class Meta:
        model = ContractIgnoreRule
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'naics_codes' in self.fields:
            instance = kwargs.get('instance')
            if instance and instance.pk and instance.rule_type == 'domain':
                # Only show the NAICS codes belonging to this specific domain
                self.fields['naics_codes'].queryset = instance.naics_codes.all().order_by('code')
            else:
                self.fields['naics_codes'].queryset = NAICSCode.objects.all().order_by('code')

class ContractIgnoreRuleAdmin(admin.ModelAdmin):
    form = ContractIgnoreRuleForm
    list_display = ('rule_type', 'value', 'should_delete', 'is_active', 'created_at')
    list_filter = ('rule_type', 'should_delete', 'is_active')
    search_fields = ('value',)
    list_editable = ('should_delete', 'is_active')
    filter_horizontal = ('naics_codes',)
    actions = ['enable_rules', 'disable_rules', 'flag_for_deletion']

    @admin.action(description='Activate selected rules (Set is_active=True)')
    def enable_rules(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Deactivate selected rules (Set is_active=False)')
    def disable_rules(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description='Flag selected rules for deletion (Set should_delete=True)')
    def flag_for_deletion(self, request, queryset):
        queryset.update(should_delete=True)


from tracker.models import NAICSCode, PSCCode


class NAICSCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'description')
    search_fields = ('code', 'description')


class PSCCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'description')
    search_fields = ('code', 'description')


custom_admin_site.register(ContractIgnoreRule, ContractIgnoreRuleAdmin)

custom_admin_site.register(NAICSCode, NAICSCodeAdmin)

custom_admin_site.register(PSCCode, PSCCodeAdmin)
