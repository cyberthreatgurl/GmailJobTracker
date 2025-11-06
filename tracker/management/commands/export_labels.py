# tracker/management/commands/export_labels.py

import csv

from django.core.management.base import BaseCommand

from tracker.models import Message, ThreadTracking  # ✅ include Message


class Command(BaseCommand):
    help = "Export labeled Applications and Messages for ML training"

    def handle(self, *args, **kwargs):
        with open("labeled_subjects.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # ✅ Add a "type" column so you know if the row came from Application or Message
            writer.writerow(["type", "id", "subject", "body", "ml_label"])

            # --- Applications ---
            for app in ThreadTracking.objects.filter(reviewed=True, ml_label__isnull=False):
                writer.writerow(
                    [
                        "application",
                        app.id,
                        getattr(app, "subject", ""),  # some apps may not have subject field
                        "",  # Applications don’t have body text
                        app.ml_label,
                    ]
                )

            # --- Messages ---
            for msg in Message.objects.filter(reviewed=True, ml_label__isnull=False):
                writer.writerow(["message", msg.id, msg.subject, msg.body, msg.ml_label])
