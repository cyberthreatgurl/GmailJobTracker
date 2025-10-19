# (Moved ML training models below imports)


# Create models here.
from django.db import models
from django.utils.timezone import now


class Company(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True)
    ats = models.CharField(
        max_length=255, blank=True, null=True
    )  # New field for ATS domain
    homepage = models.URLField(max_length=512, blank=True, null=True)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    contact_email = models.EmailField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=32,
        choices=[
            ("application", "Application"),
            ("interview", "Interview"),
            ("follow-up", "Follow-up"),
            ("rejected", "Rejected"),
            ("ghosted", "Ghosted"),
        ],
        blank=True,
        null=True,
        default="application",
    )
    first_contact = models.DateTimeField()
    last_contact = models.DateTimeField()
    confidence = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name

    def message_count(self):
        return self.message_set.count()

    def application_count(self):
        return self.application_set.count()


class Application(models.Model):
    thread_id = models.CharField(max_length=255, unique=True)
    company_source = models.CharField(max_length=50, blank=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    job_title = models.CharField(max_length=255)
    job_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=50)
    sent_date = models.DateField()
    rejection_date = models.DateField(null=True, blank=True)
    interview_date = models.DateField(null=True, blank=True)
    ml_label = models.CharField(
        max_length=50, blank=True, null=True
    )  # e.g., job_alert, noise
    ml_confidence = models.FloatField(blank=True, null=True)
    reviewed = models.BooleanField(default=False)

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

    # Manual labeling for ML
    ml_label = models.CharField(max_length=50, null=True, blank=True)  # NEW
    confidence = models.FloatField(null=True, blank=True)  # ✅ NEW
    reviewed = models.BooleanField(default=False)  # NEW

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
