# tracker/management/commands/export_labels.py

import csv
from django.core.management.base import BaseCommand
from tracker.models import Application

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        with open("labeled_subjects.csv", "w") as f:
            writer = csv.writer(f)
            writer.writerow(["subject", "ml_label"])
            for app in Application.objects.filter(reviewed=True):
                writer.writerow([app.subject, app.ml_label])