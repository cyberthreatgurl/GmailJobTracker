import json
import os
from email.utils import parseaddr
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef, Q

from tracker.models import Company, Message, ThreadTracking


class Command(BaseCommand):
    help = "Delete Application records that belong to headhunter companies, Glassdoor noreply, or have HH triggers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without applying changes",
        )
        parser.add_argument(
            "--verbose", action="store_true", help="Print detailed listing and triggers"
        )
        parser.add_argument(
            "--company-id",
            type=int,
            help="Limit to a specific company id for diagnostics/purge",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        verbose = options.get("verbose", False)
        company_id_filter = options.get("company_id")

        # Load safety configuration from companies.json
        headhunter_domains = []
        ats_domains = []
        domain_to_company = {}
        companies_path = Path("json/companies.json")
        if companies_path.exists():
            try:
                with open(companies_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    headhunter_domains = [
                        d.strip().lower()
                        for d in data.get("headhunter_domains", [])
                        if d and isinstance(d, str)
                    ]
                    ats_domains = [
                        d.strip().lower()
                        for d in data.get("ats_domains", [])
                        if d and isinstance(d, str)
                    ]
                    # Map of domain -> canonical company name
                    raw_map = data.get("domain_to_company", {}) or {}
                    # Normalize keys to lowercase
                    domain_to_company = {
                        (k or "").strip().lower(): (v or "").strip()
                        for k, v in raw_map.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"Warning: could not read companies.json: {e}")
                )

        # Identify headhunter companies strictly by their own domain or name
        hh_company_q = Q(name__iexact="HeadHunter")
        for d in headhunter_domains:
            hh_company_q |= Q(domain__iendswith=d)
        hh_company_ids = list(
            Company.objects.filter(hh_company_q).values_list("id", flat=True)
        )

        # Detect headhunter-origin threads via Message: same thread_id and HH sender or HH label
        msg_hh_q = Q(ml_label="head_hunter")
        for d in headhunter_domains:
            msg_hh_q |= Q(sender__icontains=f"@{d}")
        hh_thread_exists = Exists(
            Message.objects.filter(thread_id=OuterRef("thread_id")).filter(msg_hh_q)
        )

        # Detect Glassdoor noreply threads
        glassdoor_thread_exists = Exists(
            Message.objects.filter(
                thread_id=OuterRef("thread_id"),
                sender__icontains="noreply@glassdoor.com",
            )
        )

        # Base queryset
        apps_qs = (
            ThreadTracking.objects.select_related("company")
            .annotate(
                hh_thread=hh_thread_exists, glassdoor_thread=glassdoor_thread_exists
            )
            .filter(
                Q(company_id__in=hh_company_ids)
                | Q(hh_thread=True)
                | Q(glassdoor_thread=True)
            )
        )
        if company_id_filter:
            apps_qs = apps_qs.filter(company_id=company_id_filter)

        # Env gates for user-sender exclusion
        user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip().lower()
        exclude_user_hh = os.environ.get(
            "HEADHUNTER_EXCLUDE_USER_SENDER", "false"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

        def _sender_domain(sender: str) -> str:
            if not sender:
                return ""
            name, addr = parseaddr(sender)
            if addr and "@" in addr:
                return addr.split("@", 1)[1].lower().strip()
            # fallback
            s = (sender or "").lower()
            at = s.rfind("@")
            if at != -1:
                dom = s[at + 1 :].strip().strip(")>")
                dom = dom.split()[0].strip(",.;")
                return dom
            return ""

        def _domain_suffixes(dom: str):
            """Yield domain suffixes from most specific to TLD-level.

            e.g., 'a.mail.amazon.com' -> 'a.mail.amazon.com', 'mail.amazon.com', 'amazon.com', 'com'
            """
            dom = (dom or "").lower().strip()
            if not dom:
                return []
            parts = dom.split(".")
            return [".".join(parts[i:]) for i in range(len(parts))]

        def _canonical_company_for_domain(dom: str) -> str:
            """Lookup canonical company name for a domain using companies.json domain_to_company mapping.

            Tries all suffixes to allow subdomain matches. Returns empty string if no mapping.
            """
            for suf in _domain_suffixes(dom):
                mapped = domain_to_company.get(suf)
                if mapped:
                    return mapped.strip()
            return ""

        def _is_ats_domain(dom: str) -> bool:
            d = (dom or "").lower().strip()
            return any(d.endswith(ad) for ad in ats_domains)

        def triggers_for_app(app):
            # Collect HH triggers
            tqs = Message.objects.filter(thread_id=app.thread_id).filter(msg_hh_q)
            if exclude_user_hh and user_email:
                tqs = tqs.exclude(sender__icontains=user_email)
            hh_triggers = list(
                tqs.values("id", "msg_id", "sender", "ml_label", "timestamp")
            )

            # Collect Glassdoor triggers
            glassdoor_triggers = list(
                Message.objects.filter(
                    thread_id=app.thread_id, sender__icontains="noreply@glassdoor.com"
                ).values("id", "msg_id", "sender", "ml_label", "timestamp")
            )

            # Combine and return all triggers
            return hh_triggers + glassdoor_triggers

        def is_safe_triggers_for_app(app, trig_msgs):
            """Safe if ALL trigger messages are from ATS domains or map to the same company as the Application.

            Rules:
            - If Application's company domain is a headhunter domain, not safe.
            - If no triggers, not safe (we rely on explicit triggers to decide safety).
            - If any trigger is from Glassdoor noreply, not safe (always delete).
            - For each trigger message domain:
              - If it's an ATS domain -> safe for that message
              - Else, if it endswith the application's company domain -> safe
              - Else, if mapped canonical company equals the application's canonical company -> safe
              - Otherwise, unsafe
            Only if all triggers are safe do we consider the Application safe (excluded from deletion).
            """
            company = getattr(app, "company", None)
            app_company_name = (company.name or "").strip().lower() if company else ""
            app_company_domain = (
                (company.domain or "").lower().strip() if company else ""
            )
            if app_company_domain and any(
                app_company_domain.endswith(d) for d in headhunter_domains
            ):
                return False
            if not trig_msgs:
                return False

            # Glassdoor noreply is never safe - always delete
            for m in trig_msgs:
                sender = (m.get("sender") or "").lower()
                if "noreply@glassdoor.com" in sender:
                    return False

            # Determine canonical company for the app by domain mapping first, then by name
            app_canonical = _canonical_company_for_domain(app_company_domain)
            if not app_canonical:
                app_canonical = app_company_name

            for m in trig_msgs:
                dom = _sender_domain(m.get("sender") or "")
                if not dom:
                    return False
                # ATS domains are safe
                if _is_ats_domain(dom):
                    continue
                # Same-domain (subdomain) safe
                if app_company_domain and dom.endswith(app_company_domain):
                    continue
                # Corporate recruiter domain mapping safe
                mapped = _canonical_company_for_domain(dom).strip().lower()
                if mapped and app_canonical and mapped == app_canonical:
                    continue
                # Otherwise, this trigger is unsafe
                return False
            return True

        # Filter to delete vs excluded-safe
        apps_to_delete = []
        apps_excluded_safe = []
        for app in apps_qs.iterator():
            trig = triggers_for_app(app)
            if is_safe_triggers_for_app(app, trig):
                apps_excluded_safe.append((app, trig))
            else:
                apps_to_delete.append((app, trig))

        def print_triggers_for_app(app, trig_msgs):
            reasons = []
            if app.company_id in hh_company_ids:
                reasons.append("company is headhunter (name/domain match)")

            # Check for Glassdoor triggers
            glassdoor_count = sum(
                1
                for m in trig_msgs
                if "noreply@glassdoor.com" in (m.get("sender") or "").lower()
            )
            if glassdoor_count:
                reasons.append(f"{glassdoor_count} Glassdoor noreply message(s)")

            # Check for other HH triggers
            hh_count = len(trig_msgs) - glassdoor_count
            if hh_count:
                reasons.append(f"{hh_count} headhunter-like message(s) in thread")

            if reasons:
                self.stdout.write("    reasons: " + "; ".join(reasons))
            for m in trig_msgs[:5]:
                self.stdout.write(
                    f"    trigger msg id={m['id']} gmail_id={m['msg_id']} sender='{m['sender']}' label={m['ml_label']} ts={m['timestamp']}"
                )

        # DRY-RUN OUTPUT
        if dry_run:
            to_delete_count = len(apps_to_delete)
            if verbose and to_delete_count:
                self.stdout.write(self.style.NOTICE("Summary by company (dry-run):"))
                summary_counter = {}
                for app, _ in apps_to_delete:
                    key = (
                        app.company_id,
                        app.company.name if app.company else "<none>",
                    )
                    summary_counter[key] = summary_counter.get(key, 0) + 1
                for (cid, cname), n in sorted(
                    summary_counter.items(), key=lambda x: (-x[1], x[0][1])
                ):
                    self.stdout.write(f"  {n} × company '{cname}' (id={cid})")

                self.stdout.write(
                    self.style.NOTICE("\nListing matching Application rows (dry-run):")
                )
                for app, trig in apps_to_delete:
                    self.stdout.write(
                        f"  id={app.id} thread={app.thread_id} company_id={app.company_id} company='{app.company.name}' sent_date={app.sent_date}"
                    )
                    print_triggers_for_app(app, trig)
                if apps_excluded_safe:
                    self.stdout.write(
                        self.style.WARNING(
                            "\nExcluded (safe triggers: same-company/corporate/ATS):"
                        )
                    )
                    for app, _ in apps_excluded_safe[:20]:
                        self.stdout.write(
                            f"  [excluded] id={app.id} thread={app.thread_id} company='{app.company.name}'"
                        )

            self.stdout.write(
                self.style.NOTICE(
                    f"Dry run: {to_delete_count} headhunter application(s) would be deleted."
                )
            )
            return

        # ACTUAL DELETE
        deleted = 0
        to_delete_count = len(apps_to_delete)
        if to_delete_count:
            if verbose:
                self.stdout.write(self.style.WARNING("Summary by company (to delete):"))
                summary_counter = {}
                for app, _ in apps_to_delete:
                    key = (
                        app.company_id,
                        app.company.name if app.company else "<none>",
                    )
                    summary_counter[key] = summary_counter.get(key, 0) + 1
                for (cid, cname), n in sorted(
                    summary_counter.items(), key=lambda x: (-x[1], x[0][1])
                ):
                    self.stdout.write(f"  {n} × company '{cname}' (id={cid})")

                self.stdout.write(
                    self.style.WARNING("\nDeleting the following Application rows:")
                )
                for app, trig in apps_to_delete:
                    self.stdout.write(
                        f"  id={app.id} thread={app.thread_id} company_id={app.company_id} company='{app.company.name}' sent_date={app.sent_date}"
                    )
                    print_triggers_for_app(app, trig)

            to_delete_ids = [app.id for app, _ in apps_to_delete]
            deleted_info = ThreadTracking.objects.filter(id__in=to_delete_ids).delete()
            deleted = deleted_info[0]

        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted} headhunter application(s).")
        )
