# tracker/forms.py
from django import forms
from django.core.validators import RegexValidator, URLValidator
from django.utils.timezone import now

from tracker.models import ThreadTracking, Company


class ApplicationEditForm(forms.ModelForm):
    class Meta:
        model = ThreadTracking
        fields = ["company", "status"]


class ManualEntryForm(forms.Form):
    """Form for manually entering NEW job applications from external sources.
    
    Note: This form only creates new applications. To update milestones 
    (prescreen, interview, rejection, offer dates), use the Application Details
    section on the Label Companies page.
    """

    # Company information
    company_select = forms.ChoiceField(
        label="Company",
        help_text="Select an existing company or choose '- New Company -' to create a new one",
        required=True,
    )
    
    new_company_name = forms.CharField(
        max_length=255,
        label="New Company Name",
        required=False,
        help_text="Enter the new company name (will be validated against existing companies and aliases)",
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s.,\-&\'"()]+$',
                message='Company name can only contain letters, numbers, spaces, and the following: . , - & \' " ( )',
                code='invalid_company_name'
            )
        ],
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate company choices from database
        from tracker.models import Company
        companies = Company.objects.all().order_by('name')
        choices = [('', '-- Select Company --'), ('__new__', '- New Company -')]
        choices.extend([(str(c.id), c.name) for c in companies])
        self.fields['company_select'].choices = choices
    
    def clean(self):
        cleaned_data = super().clean()
        company_select = cleaned_data.get('company_select')
        new_company_name = cleaned_data.get('new_company_name', '').strip()
        
        # Validate that a company is selected
        if not company_select:
            raise forms.ValidationError({
                'company_select': 'Please select a company or create a new one.'
            })
        
        # If new company selected, validate the name
        if company_select == '__new__':
            if not new_company_name:
                raise forms.ValidationError({
                    'new_company_name': 'Please enter a company name or select an existing company.'
                })
            
            # Validate against existing companies and aliases
            from tracker.models import Company, CompanyAlias
            
            # Check exact match (case-insensitive)
            existing = Company.objects.filter(name__iexact=new_company_name).first()
            if existing:
                raise forms.ValidationError({
                    'new_company_name': f'A company named "{existing.name}" already exists. Please select it from the dropdown.'
                })
            
            # Check aliases
            alias = CompanyAlias.objects.filter(alias__iexact=new_company_name).first()
            if alias:
                raise forms.ValidationError({
                    'new_company_name': f'"{new_company_name}" is an alias for "{alias.company.name}". Please select "{alias.company.name}" from the dropdown.'
                })
        
        return cleaned_data

    # Job details
    job_title = forms.CharField(
        max_length=255,
        required=False,
        label="Job Title",
        help_text="Optional: Position title",
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s.,\-/()]+$',
                message='Job title can only contain letters, numbers, spaces, and: . , - / ( )',
                code='invalid_job_title'
            )
        ],
    )

    job_id = forms.CharField(
        max_length=255,
        required=False,
        label="Job ID/Reference",
        help_text="Optional: Job posting ID or reference number",
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\-_]+$',
                message='Job ID can only contain letters, numbers, hyphens, and underscores',
                code='invalid_job_id'
            )
        ],
    )

    # Dates
    application_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=now,
        label="Application Date",
        help_text="When you submitted this application",
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
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s.,\-]+$',
                message='Source can only contain letters, numbers, spaces, and: . , -',
                code='invalid_source'
            )
        ],
    )

    def clean_company_name(self):
        """Normalize company name."""
        name = self.cleaned_data["company_name"].strip()
        return name


class UploadEmlForm(forms.Form):
    eml_file = forms.FileField(
        label=".eml file", help_text="Upload complete .eml file including headers"
    )
    thread_id = forms.CharField(
        max_length=255,
        required=False,
        label="Thread ID override",
        help_text="Optional: force thread_id to use for this message",
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9]+$',
                message='Thread ID can only contain letters and numbers',
                code='invalid_thread_id'
            )
        ],
    )
    no_tt = forms.BooleanField(
        required=False,
        initial=False,
        label="Do not create ThreadTracking",
        help_text="When checked, do not auto-create a ThreadTracking record",
    )


class CompanyEditForm(forms.ModelForm):
    """Form for editing Company details in label_companies view."""

    # Add career_url as a non-model field
    career_url = forms.URLField(
        max_length=512,
        required=False,
        label="Career Page URL",
        help_text="Company's job listings or career page",
        validators=[URLValidator(schemes=['http', 'https'])],
    )
    
    # Add alias as a non-model field
    alias = forms.CharField(
        max_length=255,
        required=False,
        label="Alias",
        help_text="Alternative name or abbreviation (e.g., 'AFS' for 'Accenture Federal Services')",
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s.,\-_&]+$',
                message='Alias can only contain letters, numbers, spaces, and: . , - _ &',
                code='invalid_alias'
            )
        ],
    )
    
    # Add focus_area as a non-model field (actually it IS in the model but we list it explicitly)
    focus_area = forms.CharField(
        max_length=255,
        required=False,
        label="Focus Area",
        help_text="Business focus area (e.g., Software as a Service, Mining, Network Security)",
    )

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
            "notes",
            "focus_area",
        ]
        help_texts = {
            "domain": "Primary company domain",
            "ats": "Applicant Tracking System domain",
            "notes": "Free-form notes about the company",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "style": "width: 100%; resize: vertical;"}),
        }
