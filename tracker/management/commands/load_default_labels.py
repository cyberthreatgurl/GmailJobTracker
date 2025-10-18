from django.core.management.base import BaseCommand
from tracker.models import MessageLabel
import json


class Command(BaseCommand):
    help = "Load default plot series labels from json/plot_series.json into MessageLabel table."

    def handle(self, *args, **options):
        with open("json/plot_series.json", "r") as f:
            labels = json.load(f)
            count = 0
            for entry in labels:
                obj, created = MessageLabel.objects.get_or_create(
                    label=entry["label"],
                    defaults={
                        "display_name": entry["display_name"],
                        "color": entry["color"],
                    },
                )
                if created:
                    count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {count} new MessageLabel(s) from plot_series.json."
            )
        )
