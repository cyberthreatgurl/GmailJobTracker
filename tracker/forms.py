from django import forms
from tracker.models import Application

class ApplicationEditForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['company', 'status']