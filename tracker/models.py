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
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    job_title = models.CharField(max_length=255)
    status = models.CharField(max_length=50)
    sent_date = models.DateField()
    rejection_date = models.DateField(null=True, blank=True)
    interview_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.company.name} – {self.job_title}"

class Message(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    sender = models.CharField(max_length=255)
    subject = models.TextField()
    body = models.TextField()
    timestamp = models.DateTimeField()
    thread_id = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.company.name} – {self.timestamp.strftime('%Y-%m-%d %H:%M')}"