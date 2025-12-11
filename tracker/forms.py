# tracker/forms.py
from django import forms
from django.utils.timezone import now

from tracker.models import ThreadTracking, Company


class ApplicationEditForm(forms.ModelForm):
    class Meta:
        model = ThreadTracking
        fields = ["company", "status"]


class ManualEntryForm(forms.Form):
    """Form for manually entering job application data from external sources."""

    # Entry type
    ENTRY_TYPES = [
        ("application", "Job Application"),
        ("interview", "Interview Invitation"),
        ("rejection", "Rejection"),
    ]
    entry_type = forms.ChoiceField(
        choices=ENTRY_TYPES,
        widget=forms.RadioSelect,
        initial="application",
        label="Entry Type",
    )

    # Company information
    company_name = forms.CharField(
        max_length=255,
        label="Company Name",
        help_text="Enter the company name (will auto-match or create new)",
    )

    # Job details
    job_title = forms.CharField(
        max_length=255,
        required=False,
        label="Job Title",
        help_text="Optional: Position title",
    )

    job_id = forms.CharField(
        max_length=255,
        required=False,
        label="Job ID/Reference",
        help_text="Optional: Job posting ID or reference number",
    )

    # Dates
    application_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=now,
        label="Application Date",
        help_text="When you applied or when this event occurred",
    )

    interview_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        label="Interview Date",
        help_text="For interview entries: scheduled interview date",
    )

    # Additional info
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        label="Notes",
        help_text="Optional: Additional details (source, contact info, etc.)",
    )

    source = forms.CharField(
        max_length=100,
        initial="manual",
        required=False,
        label="Source",
        help_text="e.g., LinkedIn, Indeed, direct, recruiter, etc.",
    )

    def clean_company_name(self):
        """Normalize company name."""
        name = self.cleaned_data["company_name"].strip()
        return name

    def clean(self):
        cleaned_data = super().clean()
        entry_type = cleaned_data.get("entry_type")
        interview_date = cleaned_data.get("interview_date")

        # Validate interview date is required for interview type
        if entry_type == "interview" and not interview_date:
            self.add_error("interview_date", "Interview date is required for interview entries.")

        return cleaned_data


class UploadEmlForm(forms.Form):
    eml_file = forms.FileField(label=".eml file", help_text="Upload complete .eml file including headers")
    thread_id = forms.CharField(max_length=255, required=False, label="Thread ID override", help_text="Optional: force thread_id to use for this message")
    no_tt = forms.BooleanField(required=False, initial=False, label="Do not create ThreadTracking", help_text="When checked, do not auto-create a ThreadTracking record")


class CompanyEditForm(forms.ModelForm):
    """Form for editing Company details in label_companies view."""

    # Add career_url as a non-model field
    career_url = forms.URLField(
        max_length=512,
        required=False,
        label="Career Page URL",
        help_text="Company's job listings or career page",
    )

    class Meta:
        model = Company
        fields = ["name", "domain", "ats", "homepage", "contact_name", "contact_email", "status"]
        help_texts = {
            "domain": "Primary company domain",
            "ats": "Applicant Tracking System domain",
        }
