# tracker/forms.py
from django import forms
from django.utils.timezone import now

from tracker.models import ThreadTracking


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
