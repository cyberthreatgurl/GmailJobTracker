import logging
from django.core.management.base import BaseCommand
from tracker.models import DefenseContract, ContractIgnoreRule
from django.db.models import Q

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Deletes DefenseContracts that match active ignore rules where should_delete is True."

    def handle(self, *args, **kwargs):
        rules = ContractIgnoreRule.objects.filter(is_active=True, should_delete=True)
        if not rules.exists():
            self.stdout.write("No active ignore rules with 'should_delete=True'.")
            return

        deleted_total = 0
        for rule in rules:
            qs = DefenseContract.objects.all()
            if rule.rule_type == 'term':
                qs = qs.filter(
                    Q(description__icontains=rule.value) |
                    Q(company_name_raw__icontains=rule.value) |
                    Q(awarding_agency__icontains=rule.value) |
                    Q(awarding_sub_agency__icontains=rule.value)
                )
            elif rule.rule_type == 'naics':
                qs = qs.filter(naics_code=rule.value)
            elif rule.rule_type == 'psc':
                qs = qs.filter(product_or_service_code=rule.value)
            elif rule.rule_type == 'domain':
                if rule.naics_codes.exists():
                    naics_list = list(rule.naics_codes.values_list('code', flat=True))
                    qs = qs.filter(naics_code__in=naics_list)
                else:
                    qs = qs.filter(
                        Q(awarding_agency__icontains=rule.value) |
                        Q(description__icontains=rule.value)
                    )

            count = qs.count()
            if count > 0:
                qs.delete()
                deleted_total += count
                self.stdout.write(f"Deleted {count} contracts matching {rule.rule_type}='{rule.value}'.")

        self.stdout.write(self.style.SUCCESS(f"Finished cleaning {deleted_total} ignored contracts."))
