from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import KnownCompany, ATSDomain, DomainToCompany, CompanyAlias, Company
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

    out_path = Path("json") / "companies.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@receiver(post_save, sender=Company)
def sync_domain_to_company_on_company_save(sender, instance: Company, **kwargs):
    """
    When a Company is saved, if it has a valid domain and name, ensure DomainToCompany is upserted.
    This keeps json/companies.json domain_to_company in sync via export_companies signal above.
    """
    name = (instance.name or "").strip()
    domain = (instance.domain or "").strip().lower()
    if not name or not domain:
        return
    # Basic normalization: strip scheme and leading www.
    for prefix in ("http://", "https://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]
    if domain.startswith("www."):
        domain = domain[4:]
    # Only proceed if it looks like a hostname
    if "." not in domain:
        return
    # Upsert mapping
    obj, _ = DomainToCompany.objects.update_or_create(
        domain=domain, defaults={"company": name}
    )
    # Trigger export
    export_companies(sender=DomainToCompany)
