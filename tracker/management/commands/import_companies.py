import json
from pathlib import Path

from django.core.management.base import BaseCommand

from tracker.models import ATSDomain, CompanyAlias, DomainToCompany, KnownCompany


class Command(BaseCommand):
    help = "Import companies.json into the database"

    def handle(self, *args, **kwargs):
        path = Path(__file__).resolve().parent.parent.parent.parent / "companies.json"
        if not path.exists():
            self.stdout.write(self.style.ERROR("companies.json not found"))
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for name in data.get("known", []):
            KnownCompany.objects.get_or_create(name=name)

        for domain in data.get("ats_domains", []):
            ATSDomain.objects.get_or_create(domain=domain)

        for domain, company in data.get("domain_to_company", {}).items():
            DomainToCompany.objects.get_or_create(domain=domain, company=company)

        for alias, company in data.get("aliases", {}).items():
            CompanyAlias.objects.get_or_create(alias=alias, company=company)

        self.stdout.write(self.style.SUCCESS("companies.json imported successfully"))
