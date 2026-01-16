from django import forms

from .models import Company, ThreadTracking


class CompanyEditForm(forms.ModelForm):
    domain = forms.CharField(required=False, label="Domain Name")
    ats = forms.CharField(required=False, label="ATS Domain (if any)")
    career_url = forms.URLField(required=False, label="Career/Jobs URL")
    focus_area = forms.CharField(required=False, label="Focus Area")

    class Meta:
        model = Company
        fields = [
            "name",
            "domain",
            "ats",
            "homepage",
            "contact_name",
            "contact_email",
            "status",
            "focus_area",
            "notes",
        ]
        widgets = {
            "status": forms.Select(choices=Company._meta.get_field("status").choices),
            "notes": forms.Textarea(attrs={
                'rows': 6,
                'style': 'width: 100%; padding: 0.75rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.95rem; resize: vertical; font-family: inherit; box-sizing: border-box;'
            }),
        }


class ApplicationDetailsForm(forms.ModelForm):
    """Form for editing application-specific details (prescreen, interview dates, etc.)"""
    
    job_title = forms.CharField(
        required=False,
        label="Job Title",
        max_length=500,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Senior Software Engineer, Product Manager'
        }),
        help_text="Title of the position you applied for"
    )
    
    sent_date = forms.DateField(
        required=False,
        label="Application Date",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        help_text="Date you submitted the application"
    )
    
    prescreen_date = forms.DateField(
        required=False,
        label="Prescreen Date",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        help_text="Date of prescreen phone call"
    )
    
    interview_date = forms.DateField(
        required=False,
        label="Interview Date",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        help_text="Date of scheduled interview"
    )
    
    rejection_date = forms.DateField(
        required=False,
        label="Rejection Date",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        help_text="Date rejection was received"
    )
    
    offer_date = forms.DateField(
        required=False,
        label="Offer Date",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        help_text="Date job offer was received"
    )
    
    application_url = forms.URLField(
        required=False,
        label="Application URL",
        max_length=500,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://company.com/job/12345'
        }),
        help_text="Link to the job posting or application"
    )
    
    application_text = forms.CharField(
        required=False,
        label="Application Text",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Cover letter or notes about your application'
        }),
        help_text="Cover letter or application notes"
    )
    
    class Meta:
        model = ThreadTracking
        fields = ['job_title', 'sent_date', 'prescreen_date', 'interview_date', 'rejection_date', 'offer_date', 'application_url', 'application_text']
    
    def clean_application_url(self):
        """Validate URL format and security"""
        url = self.cleaned_data.get('application_url')
        if url:
            url = url.strip()
            # Ensure it's a valid HTTP/HTTPS URL
            if not url.startswith(('http://', 'https://')):
                raise forms.ValidationError("URL must start with http:// or https://")
            # Basic length check
            if len(url) > 500:
                raise forms.ValidationError("URL is too long (max 500 characters)")
        return url
    
    def clean_application_text(self):
        """Validate and sanitize application text"""
        text = self.cleaned_data.get('application_text')
        if text:
            text = text.strip()
            # Limit length to prevent abuse
            if len(text) > 20000:
                raise forms.ValidationError("Application text is too long (max 20,000 characters)")
        return text

