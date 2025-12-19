import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Q

from tracker.models import Company, Message

BLOCKED_LABELS = {
    "job_application",
    "application",
    "interview_invite",
    "rejected",
    "rejection",
}


class Command(BaseCommand):
    help = "Normalize labels for headhunter messages: prevent job_application/interview/rejected on HH; set to head_hunter."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without saving",
        )
        parser.add_argument(
            "--company-id", type=int, help="Restrict to a specific company id"
        )
        parser.add_argument(
            "--verbose", action="store_true", help="Print detailed listings"
        )

    def handle(self, *args, **opts):
        dry_run = opts.get("dry_run", False)
        company_id = opts.get("company_id")
        verbose = opts.get("verbose", False)

        # Load headhunter domains
        headhunter_domains = []
        try:
            companies_path = Path("json/companies.json")
            if companies_path.exists():
                with open(companies_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    headhunter_domains = [
                        (d or "").strip().lower()
                        for d in data.get("headhunter_domains", [])
                        if isinstance(d, str)
                    ]
        except Exception:
            headhunter_domains = []

        # Headhunter company filter
        hh_company_q = Q(status="headhunter") | Q(name__iexact="HeadHunter")
        for d in headhunter_domains:
            hh_company_q |= Q(domain__iendswith=d)
        hh_company_ids = list(
            Company.objects.filter(hh_company_q).values_list("id", flat=True)
        )

        # Message-based filter: sender domain indicates headhunter or company is headhunter
        msg_hh_q = Q(ml_label__in=BLOCKED_LABELS) & (
            Q(company_id__in=hh_company_ids)
            | Q(
                sender__iregex=r"@("
                + "|".join(map(lambda s: s.replace(".", r"\."), headhunter_domains))
                + ")"
            )
        )

        qs = Message.objects.filter(msg_hh_q)
        if company_id:
            qs = qs.filter(company_id=company_id)

        count = qs.count()
        self.stdout.write(
            self.style.NOTICE(f"Found {count} headhunter messages with blocked labels.")
        )

        if verbose and count:
            for m in qs.select_related("company").order_by("-timestamp")[:200]:
                self.stdout.write(
                    f"  id={m.id} company={m.company.name if m.company else None} label={m.ml_label} sender={m.sender} ts={m.timestamp}"
                )

        if not count:
            return

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run: no changes made."))
            return

        updated = 0
        try:
            from tracker.label_helpers import label_message_and_propagate
        except Exception:
            label_message_and_propagate = None

        for m in qs.iterator():
            try:
                m.reviewed = True
                if label_message_and_propagate:
                    # We're setting reviewed and the label together; force the update
                    label_message_and_propagate(
                        m, "head_hunter", confidence=1.0, overwrite_reviewed=True
                    )
                else:
                    m.ml_label = "head_hunter"
                    m.save(update_fields=["ml_label", "reviewed"])
                updated += 1
            except Exception:
                # continue on individual failure
                continue
        self.stdout.write(
            self.style.SUCCESS(f"Updated {updated} messages to head_hunter.")
        )
