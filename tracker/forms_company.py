from django import forms

from .models import Company


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
        ]
        widgets = {
            "status": forms.Select(choices=Company._meta.get_field("status").choices),
        }
