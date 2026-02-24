# (Moved ML training models below imports)


# Create models here.
from django.db import models
from django.core.validators import RegexValidator, URLValidator
from django.utils.timezone import now
from django.utils import timezone
import re

from django.utils import timezone
from tracker.location_normalization import canonicalize_city_key

class Company(models.Model):
    name = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s.,\-&\'"()]+$',
                message='Company name can only contain letters, numbers, spaces, and: . , - & \' " ( )',
                code='invalid_company_name'
            )
        ]
    )
    domain = models.CharField(
        max_length=255,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9.\-]+$',
                message='Domain can only contain letters, numbers, dots, and hyphens',
                code='invalid_domain'
            )
        ]
    )
    ats = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9.\-]+$',
                message='ATS domain can only contain letters, numbers, dots, and hyphens',
                code='invalid_ats'
            )
        ]
    )  # New field for ATS domain
    homepage = models.URLField(
        max_length=512,
        blank=True,
        null=True,
        validators=[URLValidator(schemes=['http', 'https'])]
    )
    contact_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z\s.,\-\']+$',
                message='Contact name can only contain letters, spaces, and: . , - \'',
                code='invalid_contact_name'
            )
        ]
    )
    contact_email = models.EmailField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=32,
        choices=[
            ("new", "New"),
            ("application", "Application"),
            ("interview", "Interview"),
            ("offer", "Offer"),
            ("follow-up", "Follow-up"),
            ("rejected", "Rejected"),
            ("ghosted", "Ghosted"),
            ("headhunter", "HeadHunter"),
        ],
        blank=True,
        null=True,
        default="application",
    )
    notes = models.TextField(blank=True, null=True, help_text="Free-form notes about the company")
    location = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Headquarters or office location (e.g., Reston, VA)"
    )
    focus_area = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Business focus area (e.g., Software as a Service, Mining, Network Security)"
    )
    first_contact = models.DateTimeField()
    last_contact = models.DateTimeField()
    confidence = models.FloatField(null=True, blank=True)
    last_job_search_date = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="Last date when user manually searched this company's job postings"
    )
    talent_network = models.BooleanField(
        default=False,
        help_text="Whether the user joined this company's talent network."
    )

    def __str__(self):
        return self.name

    def message_count(self):
        return self.message_set.count()

    def application_count(self):
        return self.threadtracking_set.count()


class CompanyOperatingCity(models.Model):
    """Additional city in which a company operates (beyond HQ location)."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="operating_cities",
    )
    city = models.CharField(max_length=255)
    normalized_city = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "normalized_city"],
                name="uniq_company_normalized_city",
            )
        ]
        indexes = [
            models.Index(fields=["company"]),
            models.Index(fields=["normalized_city"]),
        ]
        ordering = ["city"]

    def save(self, *args, **kwargs):
        """Normalize city for case-insensitive dedupe and searching."""
        cleaned = re.sub(r"\s+", " ", (self.city or "").strip())
        self.city = cleaned
        self.normalized_city = canonicalize_city_key(cleaned)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company.name} - {self.city}"


class CompanyNews(models.Model):
    """
    Stores recent news articles for a company.

    Aggregates articles from multiple providers (Google News RSS, NewsAPI)
    with caching and historical tracking. Allows users to research companies
    on the label_companies page.

    Fields:
    - articles: Current cached articles (JSON, limited to display_limit)
    - all_articles: Historical record of all articles ever fetched (JSON)
    - last_fetched: When news was last refreshed
    - error_message: Last error encountered during fetch (if any)
    - cache_duration_hours: How long to cache before refreshing (default: 24)
    """

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='news'
    )
    articles = models.JSONField(
        default=list,
        help_text='Currently cached articles (limited list for display)'
    )
    all_articles = models.JSONField(
        default=list,
        help_text='Historical record of all articles ever fetched'
    )
    last_fetched = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When news was last refreshed'
    )
    error_message = models.TextField(
        blank=True,
        default='',
        help_text='Last error encountered during fetch (if any)'
    )
    cache_duration_hours = models.PositiveIntegerField(
        default=24,
        help_text='How many hours before cache expires and refresh needed'
    )
    hidden_urls = models.JSONField(
        default=list,
        help_text='URLs the user has explicitly hidden from Recent News'
    )
    user_articles = models.JSONField(
        default=list,
        help_text='Articles manually added by the user (not from RSS/API)'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Company News'
        indexes = [
            models.Index(fields=['company']),
            models.Index(fields=['last_fetched']),
        ]

    def __str__(self):
        return f"News for {self.company.name}"

    def is_cache_fresh(self) -> bool:
        """Check if cached articles are still valid."""
        if not self.last_fetched:
            return False

        age = timezone.now() - self.last_fetched
        return age.total_seconds() < (self.cache_duration_hours * 3600)

    def get_display_articles(self) -> list:
        """Get articles to display (limited, sorted by date)."""
        if not self.articles:
            return []

        # Sort by date descending
        sorted_articles = sorted(
            self.articles,
            key=lambda x: x.get('date', ''),
            reverse=True
        )

        # Return up to 5 for display
        return sorted_articles[:5]

    def get_all_articles(self) -> list:
        """Get complete historical record of all articles."""
        return self.all_articles or []

    def add_articles(self, new_articles: list) -> None:
        """
        Add new articles to both current cache and historical record.

        Args:
            new_articles: List of article dicts with title, url, date, source
        """
        # Update current articles
        self.articles = new_articles

        # Add to historical record (avoiding duplicates by URL)
        existing_urls = {a['url'] for a in self.all_articles}
        for article in new_articles:
            if article['url'] not in existing_urls:
                self.all_articles.append(article)

        self.updated_at = timezone.now()


class ThreadTracking(models.Model):
    """
    Tracks a Gmail thread related to a job application.

    One ThreadTracking record = one email conversation thread about a job.
    Multiple Message records can belong to the same thread_id.

    This model aggregates thread-level information:
    - Job metadata (title, job_id parsed from subject)
    - Status lifecycle (application → interview → ghosted/rejected)
    - Key milestone dates (sent, interview, rejection)

    Used for dashboard metrics and status tracking.
    For individual email content, see the Message model.
    """

    thread_id = models.CharField(
        max_length=255,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9]+$',
                message='Thread ID can only contain letters and numbers',
                code='invalid_thread_id'
            )
        ]
    )
    company_source = models.CharField(max_length=50, blank=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    job_title = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s.,\-/()&]+$',
                message='Job title can only contain letters, numbers, spaces, and: . , - / ( ) &',
                code='invalid_job_title'
            )
        ]
    )
    location = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Job location (e.g., Remote, New York, NY, Hybrid - San Francisco)"
    )
    job_id = models.CharField(
        max_length=255,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\-_]*$',
                message='Job ID can only contain letters, numbers, hyphens, and underscores',
                code='invalid_job_id'
            )
        ]
    )
    status = models.CharField(max_length=50)
    sent_date = models.DateField()
    rejection_date = models.DateField(null=True, blank=True)
    cancelled = models.BooleanField(
        default=False,
        help_text="Job posting was cancelled by the company"
    )
    withdrew = models.BooleanField(
        default=False,
        help_text="User withdrew their application"
    )
    prescreen_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of prescreen phone call or initial screening"
    )
    interview_date = models.DateField(null=True, blank=True)
    offer_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date job offer was received"
    )
    interview_completed = models.BooleanField(default=False)
    application_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL to the job application page"
    )
    application_text = models.TextField(
        blank=True,
        null=True,
        help_text="Cover letter or application text"
    )
    ml_label = models.CharField(max_length=50, blank=True, null=True)  # e.g., noise
    ml_confidence = models.FloatField(blank=True, null=True)
    reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = "tracker_application"  # Keep existing table name to preserve data
        verbose_name = "Thread Tracking"
        verbose_name_plural = "Thread Tracking"

    def __str__(self):
        return f"{self.company.name} - {self.job_title}"


class MessageLabel(models.Model):
    label = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    color = models.CharField(max_length=16, default="#2563eb")

    def __str__(self):
        return f"{self.label} ({self.display_name})"


class Message(models.Model):
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL
    )
    company_source = models.CharField(
        max_length=50, null=True, blank=True
    )  # ✅ Add this
    sender = models.CharField(max_length=255)
    subject = models.TextField()
    body = models.TextField()
    body_html = models.TextField(blank=True, null=True)  # new field

    timestamp = models.DateTimeField()

    # Gmail identifiers
    msg_id = models.CharField(
        max_length=255, unique=True
    )  # NEW: unique Gmail messageId
    thread_id = models.CharField(
        max_length=255, db_index=True
    )  # keep, but index for grouping
    body_hash = models.CharField(
        max_length=64, db_index=True, null=True, blank=True
    )  # SHA256 hash for deduplication

    # Manual labeling for ML
    ml_label = models.CharField(max_length=50, null=True, blank=True)  # NEW
    confidence = models.FloatField(null=True, blank=True)  # ✅ NEW
    reviewed = models.BooleanField(default=False)  # NEW
    classification_source = models.CharField(
        max_length=20, null=True, blank=True
    )  # 'ml', 'rule', 'rules_override', 'rules'

    def save(self, *args, **kwargs):
        """Override save to ensure reviewed noise messages have no company."""
        # Clear company for noise messages only when reviewed
        # (allows inspection during model training/testing)
        if self.ml_label == "noise" and self.reviewed:
            self.company = None
            self.company_source = ""
        super().save(*args, **kwargs)

    @property
    def sender_domain(self):
        """Extract the domain from the sender email address.
        
        Handles formats like:
        - "Display Name" <email@domain.com>
        - email@domain.com
        - "Name @ Company" <email@domain.com>
        """
        from email.utils import parseaddr
        import re
        
        _, email_addr = parseaddr(self.sender)
        if email_addr and "@" in email_addr:
            return email_addr.split("@", 1)[1].strip(">").lower()
        # Fallback: try to find email pattern in sender
        match = re.search(r"@([A-Za-z0-9.-]+)", self.sender)
        if match:
            return match.group(1).lower()
        return ""

    def __str__(self):
        company_name = self.company.name if self.company else "No Company"
        return f"{company_name} – {self.timestamp.strftime('%Y-%m-%d %H:%M')}"


class IgnoredMessage(models.Model):
    msg_id = models.CharField(max_length=128, unique=True)
    subject = models.TextField()
    body = models.TextField()
    company_source = models.CharField(max_length=50, blank=True)
    sender = models.CharField(max_length=256)
    sender_domain = models.CharField(max_length=256)
    date = models.DateTimeField()
    reason = models.CharField(max_length=128)  # e.g., 'ml_ignore', 'low_confidence'
    logged_at = models.DateTimeField(auto_now_add=True)


class IngestionStats(models.Model):
    date = models.DateField(primary_key=True)
    total_fetched = models.IntegerField(default=0)
    total_inserted = models.IntegerField(default=0)
    total_ignored = models.IntegerField(default=0)
    total_skipped = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)


class UnresolvedCompany(models.Model):
    msg_id = models.CharField(max_length=128, unique=True)
    subject = models.TextField()
    body = models.TextField()
    sender = models.CharField(max_length=256)
    sender_domain = models.CharField(max_length=256)
    timestamp = models.DateTimeField()
    notes = models.TextField(blank=True, null=True)
    reviewed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.msg_id} ({self.sender_domain})"


class KnownCompany(models.Model):
    name = models.CharField(max_length=255, unique=True)


class ATSDomain(models.Model):
    domain = models.CharField(max_length=255, unique=True)


class DomainToCompany(models.Model):
    domain = models.CharField(max_length=255, unique=True)
    company = models.CharField(max_length=255)


class CompanyAlias(models.Model):
    alias = models.CharField(max_length=255, unique=True)
    company = models.CharField(max_length=255)


class Ticket(models.Model):
    CATEGORY_CHOICES = [
        ("code", "Code Problem"),
        ("admin_ui", "Admin Site Web Problem"),
        ("upgrade", "Admin Site Upgrade"),
    ]

    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("wont_fix", "Won't Fix"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.category}] {self.title}"


class ProcessedMessage(models.Model):
    gmail_id = models.CharField(max_length=255, unique=True, db_index=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["gmail_id"])]


class GmailFilterImportLog(models.Model):
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    uploaded_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    original_filename = models.CharField(max_length=255, blank=True)
    labels_updated = models.IntegerField(default=0)
    excludes_updated = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    unmatched_labels = models.TextField(blank=True)  # JSON array
    diff_json = models.TextField(blank=True)  # JSON of before/after or added lists
    notes = models.TextField(blank=True)

    def __str__(self):
        who = self.uploaded_by.username if self.uploaded_by else "system"
        return f"Filters import on {self.uploaded_at:%Y-%m-%d %H:%M} by {who}"


# --- ML Model Training Tracking ---
class ModelTrainingRun(models.Model):
    trained_at = models.DateTimeField(default=now, db_index=True)
    n_samples = models.IntegerField()
    n_classes = models.IntegerField()
    accuracy = models.FloatField(null=True, blank=True)
    macro_precision = models.FloatField(null=True, blank=True)
    macro_recall = models.FloatField(null=True, blank=True)
    macro_f1 = models.FloatField(null=True, blank=True)
    weighted_precision = models.FloatField(null=True, blank=True)
    weighted_recall = models.FloatField(null=True, blank=True)
    weighted_f1 = models.FloatField(null=True, blank=True)
    label_distribution = models.TextField()  # JSON or pretty string
    classification_report = models.TextField()  # Full sklearn report

    def __str__(self):
        return f"ModelTrainingRun {self.trained_at.strftime('%Y-%m-%d %H:%M:%S')} ({self.n_samples} samples)"


# Optionally, per-label metrics for each run
class ModelTrainingLabelMetric(models.Model):
    run = models.ForeignKey(
        ModelTrainingRun, on_delete=models.CASCADE, related_name="label_metrics"
    )
    label = models.CharField(max_length=64)
    precision = models.FloatField(null=True, blank=True)
    recall = models.FloatField(null=True, blank=True)
    f1 = models.FloatField(null=True, blank=True)
    support = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.label} ({self.run.trained_at.strftime('%Y-%m-%d %H:%M:%S')})"


class AppSetting(models.Model):
    """Simple key/value settings store editable via UI.

    Example keys:
    - GHOSTED_DAYS_THRESHOLD: int (1..3650)
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["key"])]

    def __str__(self):
        return f"{self.key}={self.value}"


class AuditEvent(models.Model):
    """Audit events for actions that change message review state or re-ingest.

    Stored as structured rows to allow querying and retention policies.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.CharField(max_length=150, blank=True, null=True)
    action = models.CharField(max_length=80)
    source = models.CharField(max_length=80, blank=True, null=True)

    # Optional message/thread identifiers
    msg_id = models.CharField(max_length=255, blank=True, null=True)
    db_id = models.IntegerField(blank=True, null=True)
    thread_id = models.CharField(max_length=255, blank=True, null=True)
    company_id = models.IntegerField(blank=True, null=True)

    # Free-form JSON details (stored as text) and error/trace fields
    details = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    trace = models.TextField(blank=True, null=True)

    pid = models.IntegerField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self):
        return f"AuditEvent {self.action} {self.msg_id or self.db_id or ''} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


def validate_file_size(value):
    """Validate that file size is under 5MB."""
    max_size = 5 * 1024 * 1024  # 5 MB
    if value.size > max_size:
        from django.core.exceptions import ValidationError
        raise ValidationError(f"File size must be under 5MB. Current size: {value.size / 1024 / 1024:.1f}MB")


def validate_file_extension(value):
    """Validate file extension is one of the allowed types."""
    import os
    from django.core.exceptions import ValidationError
    
    ext = os.path.splitext(value.name)[1].lower()
    allowed_extensions = ['.pdf', '.txt', '.xlsx', '.docx']
    if ext not in allowed_extensions:
        raise ValidationError(
            f"File type '{ext}' not allowed. Allowed types: {', '.join(allowed_extensions)}"
        )


def company_document_path(instance, filename):
    """Generate upload path: company_documents/<company_id>/<filename>"""
    return f"company_documents/{instance.company.id}/{filename}"


class CompanyDocument(models.Model):
    """Documents attached to a company (contracts, offers, etc.)."""
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="documents"
    )
    file = models.FileField(
        upload_to=company_document_path,
        validators=[validate_file_size, validate_file_extension],
        help_text="Allowed types: PDF, TXT, XLSX, DOCX. Max size: 5MB."
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Brief description of the document (e.g., 'Offer Letter', 'Contract')"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["-uploaded_at"]
    
    def __str__(self):
        return f"{self.company.name} - {self.filename}"
    
    @property
    def filename(self):
        """Return just the filename without the path."""
        import os
        return os.path.basename(self.file.name)
    
    @property
    def file_extension(self):
        """Return the file extension."""
        import os
        return os.path.splitext(self.file.name)[1].lower()
    
    @property
    def file_size_display(self):
        """Return human-readable file size."""
        try:
            size = self.file.size
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            else:
                return f"{size / 1024 / 1024:.1f} MB"
        except Exception:
            return "Unknown"


class DefenseContract(models.Model):
    """
    A single government contract award from war.gov (DoD) or USASpending.gov (all agencies).

    Each record represents either:
    - War.gov: One contract paragraph from a daily DoD contract announcement
    - USASpending: One contract award record from USASpending.gov API

    Fields are extracted via:
    - War.gov: Regex parsing of contract text
    - USASpending: API JSON response mapping

    The optional FK to Company links awards to tracked companies.
    """

    BRANCH_CHOICES = [
        ("army", "Army"),
        ("navy", "Navy"),
        ("air_force", "Air Force"),
        ("defense_logistics_agency", "Defense Logistics Agency"),
        ("special_operations", "U.S. Special Operations Command"),
        ("missile_defense", "Missile Defense Agency"),
        ("other", "Other"),
    ]
    
    DATA_SOURCE_CHOICES = [
        ("war_gov", "War.gov (DoD)"),
        ("usaspending", "USASpending.gov"),
    ]

    # Data source tracking (NEW for v2.0)
    data_source = models.CharField(
        max_length=20,
        choices=DATA_SOURCE_CHOICES,
        default="war_gov",
        help_text="Source of this contract record",
        db_index=True,
    )
    
    award_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="USASpending Award ID (e.g., W912GY22C0021). Empty for war.gov records.",
    )
    
    generated_internal_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="USASpending generated internal ID for award detail pages (e.g., CONT_AWD_W912GY22C0021_9700_...). Used to construct award URLs. Empty for war.gov records.",
    )
    
    usaspending_published = models.BooleanField(
        default=False,
        help_text="Whether this award's detail page is published on USASpending.gov. Always False for war.gov records.",
    )

    # Identifiers
    contract_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Contract or modification number (e.g., W9124P-22-F-0036)"
    )
    source_url = models.URLField(
        max_length=512,
        help_text="URL of the source article or USASpending award page"
    )
    article_date = models.DateField(
        help_text="Publication date of the war.gov contracts article"
    )

    # Company info (raw from scrape + optional FK)
    company_name_raw = models.CharField(
        max_length=255,
        help_text="Company name exactly as it appears in the contract text"
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="defense_contracts",
        help_text="Link to a tracked Company record, if matched"
    )

    # Contract details
    branch = models.CharField(
        max_length=40,
        choices=BRANCH_CHOICES,
        default="other",
        help_text="Military branch or agency awarding the contract (DoD classification)"
    )
    
    # Agency info (NEW for USASpending integration)
    awarding_agency = models.CharField(
        max_length=255,
        blank=True,
        help_text="Top-level agency (e.g., Department of Defense, Department of Homeland Security)",
    )
    
    awarding_sub_agency = models.CharField(
        max_length=255,
        blank=True,
        help_text="Sub-agency or bureau (e.g., Army Corps of Engineers)",
    )
    
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Dollar value of the contract award"
    )
    description = models.TextField(
        blank=True,
        help_text="Full description of the contract work"
    )
    raw_text = models.TextField(
        blank=True,
        help_text="Complete unprocessed paragraph text from the article"
    )

    # Location and timeline
    company_location = models.CharField(
        max_length=255,
        blank=True,
        help_text="City, State of the awardee (e.g., Reston, Virginia)"
    )
    work_location = models.TextField(
        blank=True,
        help_text="Where the work will be performed (may include percentages)"
    )
    
    place_of_performance_state = models.CharField(
        max_length=2,
        blank=True,
        help_text="Two-letter state code for work location (NEW for USASpending)",
    )
    
    completion_date = models.CharField(
        max_length=100,
        blank=True,
        help_text="Expected completion date as stated in the contract text"
    )
    contracting_activity = models.CharField(
        max_length=255,
        blank=True,
        help_text="Contracting command or office (e.g., Naval Air Systems Command)"
    )

    # Metadata
    is_modification = models.BooleanField(
        default=False,
        help_text="True if this is a modification to an existing contract"
    )
    is_small_business = models.BooleanField(
        default=False,
        help_text="True if the awardee is marked with * (small business)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-article_date", "branch", "company_name_raw"]
        verbose_name = "Government Contract"
        verbose_name_plural = "Government Contracts"
        indexes = [
            models.Index(fields=["article_date"]),
            models.Index(fields=["company_name_raw"]),
            models.Index(fields=["branch"]),
            models.Index(fields=["data_source", "article_date"]),  # NEW: Filter by source + date
            models.Index(fields=["awarding_agency"]),  # NEW: Agency filtering
        ]
        constraints = [
            # War.gov unique constraint (original)
            models.UniqueConstraint(
                fields=["source_url", "company_name_raw", "contract_number"],
                condition=models.Q(data_source="war_gov"),
                name="unique_wargov_contract",
            ),
            # USASpending unique constraint (NEW)
            models.UniqueConstraint(
                fields=["data_source", "award_id"],
                condition=models.Q(data_source="usaspending") & ~models.Q(award_id=""),
                name="unique_usaspending_award",
            ),
        ]

    def __str__(self):
        amount_str = f"${self.amount:,.2f}" if self.amount else "N/A"
        return f"{self.company_name_raw} – {amount_str} ({self.branch})"

    @property
    def amount_display(self):
        """Return formatted dollar amount."""
        if self.amount is None:
            return "N/A"
        if self.amount >= 1_000_000_000:
            return f"${self.amount / 1_000_000_000:,.2f}B"
        if self.amount >= 1_000_000:
            return f"${self.amount / 1_000_000:,.1f}M"
        return f"${self.amount:,.0f}"


class ScrapedArticle(models.Model):
    """
    Tracks which war.gov contract articles have already been fetched.

    Prevents redundant HTTP requests to war.gov on repeated scraping runs.
    An article is recorded after its HTML has been successfully fetched and
    parsed, regardless of how many contracts were extracted.

    Set force_refresh=True in scrape_latest() to re-fetch all articles.
    """

    url = models.URLField(
        max_length=512,
        unique=True,
        help_text="Full URL of the war.gov article page",
    )
    title = models.CharField(
        max_length=300,
        blank=True,
        help_text="Article title (e.g., 'Contracts for Feb. 5, 2026')",
    )
    article_date = models.DateField(
        null=True,
        blank=True,
        help_text="Parsed publication date of the article",
    )
    contracts_found = models.PositiveIntegerField(
        default=0,
        help_text="Number of contracts parsed from this article",
    )
    scraped_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this article was last scraped",
    )

    class Meta:
        ordering = ["-article_date", "-scraped_at"]
        indexes = [
            models.Index(fields=["article_date"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.contracts_found} contracts)"
