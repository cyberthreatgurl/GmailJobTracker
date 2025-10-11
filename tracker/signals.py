from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import KnownCompany, ATSDomain, DomainToCompany, CompanyAlias
import json
from pathlib import Path

@receiver([post_save, post_delete], sender=KnownCompany)
@receiver([post_save, post_delete], sender=ATSDomain)
@receiver([post_save, post_delete], sender=DomainToCompany)
@receiver([post_save, post_delete], sender=CompanyAlias)
def export_companies(sender, **kwargs):
    known = list(KnownCompany.objects.values_list("name", flat=True))
    ats_domains = list(ATSDomain.objects.values_list("domain", flat=True))
    domain_to_company = {
        d["domain"]: d["company"]
        for d in DomainToCompany.objects.values("domain", "company")
    }
    aliases = {
        a["alias"]: a["company"]
        for a in CompanyAlias.objects.values("alias", "company")
    }

    data = {
        "ats_domains": ats_domains,
        "known": known,
        "domain_to_company": domain_to_company,
        "aliases": aliases,
    }

    with open("companies.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)