# Create models here.
from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True)
    first_contact = models.DateTimeField()
    last_contact = models.DateTimeField()

    def __str__(self):
        return self.name

class Application(models.Model):
    thread_id = models.CharField(max_length=255, unique=True)
    company_source = models.CharField(max_length=50, blank=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    job_title = models.CharField(max_length=255)
    status = models.CharField(max_length=50)
    sent_date = models.DateField()
    rejection_date = models.DateField(null=True, blank=True)
    interview_date = models.DateField(null=True, blank=True)
    ml_label = models.CharField(max_length=50, blank=True, null=True)  # e.g., job_alert, noise
    ml_confidence = models.FloatField(blank=True, null=True)
    reviewed = models.BooleanField(default=False)
    def __str__(self):
        return f"{self.company.name} – {self.job_title}"

class Message(models.Model):
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL
    )
    sender = models.CharField(max_length=255)
    subject = models.TextField()
    body = models.TextField()
    timestamp = models.DateTimeField()

    # Gmail identifiers
    msg_id = models.CharField(max_length=255, unique=True)  # NEW: unique Gmail messageId
    thread_id = models.CharField(max_length=255, db_index=True)   # keep, but index for grouping

    # Manual labeling for ML
    ml_label = models.CharField(max_length=50, null=True, blank=True)  # NEW
    confidence = models.FloatField(null=True, blank=True)   # ✅ NEW
    reviewed = models.BooleanField(default=False)                      # NEW

    def __str__(self):
        company_name = self.company.name if self.company else "No Company"
        return f"{company_name} – {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
        
class IgnoredMessage(models.Model):
    msg_id = models.CharField(max_length=128, unique=True)
    subject = models.TextField()
    body = models.TextField()
    sender = models.CharField(max_length=256)
    sender_domain = models.CharField(max_length=256)
    date = models.DateTimeField()
    reason = models.CharField(max_length=128)  # e.g., 'ml_ignore', 'low_confidence'
    logged_at = models.DateTimeField(auto_now_add=True)    
    
class IngestionStats(models.Model):
    date = models.DateField(auto_now_add=True)
    total_fetched = models.IntegerField(default=0)
    total_inserted = models.IntegerField(default=0)
    total_ignored = models.IntegerField(default=0)
    total_skipped = models.IntegerField(default=0)