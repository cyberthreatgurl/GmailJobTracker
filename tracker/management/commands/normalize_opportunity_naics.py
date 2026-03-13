"""
Management command to normalize naics_code values on SamGovOpportunity records.

Some records (typically CSV-imported) have the full NAICS description stored in
the naics_code field (e.g. "Janitorial Services") instead of the numeric code
(e.g. "561720"). This breaks all NAICS-based ignore-rule filtering.

Usage:
    python manage.py normalize_opportunity_naics          # dry run
    python manage.py normalize_opportunity_naics --apply  # apply changes
"""
import re
from django.core.management.base import BaseCommand
from tracker.models import SamGovOpportunity, NAICSCode


class Command(BaseCommand):
    help = "Normalize non-numeric naics_code values to their corresponding codes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Actually apply changes (default: dry run).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        dry_run = not apply

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN – no changes will be saved. Pass --apply to commit."))

        # Build description → code lookup from NAICSCode table (case-insensitive)
        desc_map = {nc.description.lower().strip(): nc.code for nc in NAICSCode.objects.all()}

        # Find records where naics_code does NOT start with digits (i.e. is a description)
        non_numeric = SamGovOpportunity.objects.exclude(naics_code__regex=r'^\d')
        non_numeric = non_numeric.exclude(naics_code__isnull=True).exclude(naics_code='')

        total = non_numeric.count()
        self.stdout.write(f"Records with non-numeric naics_code: {total}")

        updated = 0
        no_match = 0

        for opp in non_numeric.only('id', 'naics_code', 'solicitation_number'):
            raw = opp.naics_code.strip()
            # Try exact match
            code = desc_map.get(raw.lower())
            if not code:
                # Partial prefix match on first 40 characters
                prefix = raw.lower()[:40]
                for desc, c in desc_map.items():
                    if desc.startswith(prefix) or prefix in desc:
                        code = c
                        break
            if code:
                if dry_run:
                    self.stdout.write(f"  WOULD update [{opp.solicitation_number}]: {raw!r} → {code}")
                else:
                    SamGovOpportunity.objects.filter(pk=opp.pk).update(naics_code=code)
                updated += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f"  No match for [{opp.solicitation_number}]: {raw!r}")
                )
                no_match += 1

        self.stdout.write(f"\nSummary: {updated} would be updated, {no_match} could not be matched.")
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Done – {updated} records updated."))
