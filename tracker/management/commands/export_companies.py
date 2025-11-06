import json
from pathlib import Path

from django.core.management.base import BaseCommand

from tracker.models import Company


class Command(BaseCommand):
    help = "Export known companies to companies.json"

    def handle(self, *args, **kwargs):
        companies = Company.objects.all().values_list("name", flat=True)
        data = {"known": sorted(set(companies))}
        path = Path("companies.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.stdout.write(f"✅ Exported {len(companies)} companies to {path}")
