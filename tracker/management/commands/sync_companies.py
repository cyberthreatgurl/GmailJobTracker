"""
Management command to synchronize Company database records with companies.json configuration.

Ensures database records have correct domain values matching companies.json mappings.
"""

import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from tracker.models import Company


class Command(BaseCommand):
    help = "Sync Company database records with companies.json configuration"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show all companies checked, not just updates",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        companies_file = Path(__file__).resolve().parent.parent.parent.parent / "json" / "companies.json"
        
        if not companies_file.exists():
            self.stdout.write(self.style.ERROR(f"❌ companies.json not found at {companies_file}"))
            return

        with open(companies_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        domain_to_company = config.get("domain_to_company", {})
        aliases = config.get("aliases", {})
        known_companies = config.get("known", [])

        if dry_run:
            self.stdout.write(self.style.WARNING("🔍 DRY RUN MODE - No changes will be made\n"))

        # Build reverse mapping: canonical_name -> [domains]
        company_domains = {}
        for domain, company_name in domain_to_company.items():
            if company_name not in company_domains:
                company_domains[company_name] = []
            company_domains[company_name].append(domain)

        # Also build alias -> canonical mapping
        alias_to_canonical = {}
        for alias_name, canonical_name in aliases.items():
            alias_to_canonical[alias_name] = canonical_name

        updated_count = 0
        checked_count = 0
        missing_in_db = []

        # Check all known companies
        for canonical_name in known_companies:
            domains = company_domains.get(canonical_name, [])
            
            # Try to find Company by canonical name or alias
            company = Company.objects.filter(name=canonical_name).first()
            
            # If not found by canonical name, try aliases
            if not company:
                for alias, canon in alias_to_canonical.items():
                    if canon == canonical_name:
                        company = Company.objects.filter(name=alias).first()
                        if company:
                            break
            
            if not company:
                if verbose or len(domains) > 0:
                    missing_in_db.append(f"{canonical_name} (domains: {', '.join(domains)})")
                continue

            checked_count += 1
            
            # Get primary domain (first one if multiple)
            primary_domain = domains[0] if domains else None
            
            if primary_domain and company.domain != primary_domain:
                if verbose or True:  # Always show updates
                    self.stdout.write(
                        f"{'[DRY RUN] ' if dry_run else ''}📝 {company.name}: "
                        f"domain '{company.domain or '(empty)'}' → '{primary_domain}'"
                    )
                
                if not dry_run:
                    company.domain = primary_domain
                    company.save(update_fields=["domain"])
                
                updated_count += 1
            elif verbose:
                self.stdout.write(f"✅ {company.name}: domain='{company.domain}' (no change)")

        # Summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write(f"📊 Summary:")
        self.stdout.write(f"   Checked: {checked_count} companies")
        self.stdout.write(f"   Updated: {updated_count} companies")
        
        if missing_in_db:
            self.stdout.write(f"   Missing in DB: {len(missing_in_db)}")
            if verbose:
                for item in missing_in_db:
                    self.stdout.write(f"      - {item}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("\n💡 Run without --dry-run to apply changes"))
        elif updated_count > 0:
            self.stdout.write(self.style.SUCCESS(f"\n✅ Successfully updated {updated_count} companies"))
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ All companies already in sync!"))
