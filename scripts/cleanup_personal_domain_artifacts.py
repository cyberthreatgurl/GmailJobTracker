#!/usr/bin/env python3
"""
Cleanup artifacts (Company, DomainToCompany, CompanyAlias) created from personal-domain messages.

Usage:
    python cleanup_personal_domain_artifacts.py [--apply] [--dry-run]

By default the script runs in dry-run mode and only reports candidates.
Use `--apply` to perform deletions/updates. Use `--yes` to skip prompts.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import timedelta

# Configure Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from django.db import transaction
from django.utils.timezone import now
from tracker.models import (
    Company,
    Message,
    ThreadTracking,
    DomainToCompany,
    CompanyAlias,
)


def load_personal_domains():
    json_path = Path(__file__).parent.parent / "json" / "personal_domains.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("domains", []))
        except Exception:
            pass

    # fallback sensible defaults
    return {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com"}


def domain_of(email_or_sender: str):
    if not email_or_sender:
        return ""
    if "@" in email_or_sender:
        return email_or_sender.split("@")[-1].lower()
    # sometimes sender is 'Name <email@domain>'
    if "<" in email_or_sender and ">" in email_or_sender:
        inside = email_or_sender.split("<")[-1].split(">")[0]
        if "@" in inside:
            return inside.split("@")[-1].lower()
    return ""


def find_domain_to_company_matches(personal_domains):
    matches = DomainToCompany.objects.filter(domain__in=personal_domains)
    return list(matches)


def find_companies_with_personal_domain(comp_domains):
    return list(Company.objects.filter(domain__in=comp_domains))


def companies_with_only_personal_messages(personal_domains):
    """Return companies where all associated messages (if any) have sender domains in personal_domains
    and there are no thread records (ThreadTracking) for the company.
    """
    candidates = []
    for company in Company.objects.all():
        msgs = Message.objects.filter(company=company)
        if msgs.count() == 0:
            # No messages — skip here; cleanup_empty_companies handles deletion
            continue

        # If any message has a non-personal sender domain, skip
        non_personal = msgs.exclude(sender__icontains="@")
        # We'll compute sender domain per message
        has_non_personal = False
        for m in msgs:
            d = domain_of(m.sender)
            if d and d not in personal_domains:
                has_non_personal = True
                break

        if has_non_personal:
            continue

        # If company has ThreadTracking records, it's likely real
        thread_count = ThreadTracking.objects.filter(company=company).count()
        if thread_count > 0:
            continue

        candidates.append({
            "company": company,
            "message_count": msgs.count(),
        })

    return candidates


def run(dry_run=True, apply_changes=False, assume_yes=False):
    personal_domains = load_personal_domains()

    print(f"Loaded {len(personal_domains)} personal domains")

    dtc_matches = find_domain_to_company_matches(personal_domains)
    comp_matches = find_companies_with_personal_domain(personal_domains)
    orphan_candidates = companies_with_only_personal_messages(personal_domains)

    print("\nSummary:\n")
    print(f"- DomainToCompany entries with personal domains: {len(dtc_matches)}")
    print(f"- Company rows whose `domain` is a personal domain: {len(comp_matches)}")
    print(f"- Companies with only personal-sender messages and no threads: {len(orphan_candidates)}")

    if dtc_matches:
        print("\nDomainToCompany examples:")
        for d in dtc_matches[:10]:
            print(f"  - {d.domain} -> {d.company}")

    if comp_matches:
        print("\nCompanies with personal `domain` examples:")
        for c in comp_matches[:10]:
            print(f"  - {c.name} (domain={c.domain}) msgs={Message.objects.filter(company=c).count()} threads={ThreadTracking.objects.filter(company=c).count()}")

    if orphan_candidates:
        print("\nCompanies likely created from personal messages (candidates):")
        for idx, ent in enumerate(orphan_candidates[:50], 1):
            c = ent["company"]
            print(f"{idx:3}. {c.id} - {c.name} domain={c.domain} msgs={ent['message_count']}")

    if dry_run and not apply_changes:
        print("\nDRY RUN: No changes will be made. Use --apply to make changes.")
        return

    # Confirmation
    if not assume_yes:
        resp = input("Proceed with applying changes? Type 'yes' to continue: ")
        if resp.lower() != "yes":
            print("Aborted by user")
            return

    # Apply changes inside a transaction
    try:
        with transaction.atomic():
            # Remove DomainToCompany entries
            dtc_deleted = 0
            if dtc_matches:
                domains = [d.domain for d in dtc_matches]
                dtc_deleted = DomainToCompany.objects.filter(domain__in=domains).delete()[0]

            # For companies whose domain is personal: if they have no non-personal messages and no threads, delete; else null out domain
            comp_deleted = 0
            comp_domain_nullified = 0
            for c in comp_matches:
                msgs = Message.objects.filter(company=c)
                # Check if any non-personal message exists
                has_non_personal = False
                for m in msgs:
                    d = domain_of(m.sender)
                    if d and d not in personal_domains:
                        has_non_personal = True
                        break

                thread_count = ThreadTracking.objects.filter(company=c).count()

                if not has_non_personal and thread_count == 0:
                    # safe to delete
                    comp_deleted += Company.objects.filter(id=c.id).delete()[0]
                else:
                    # just clear domain to avoid showing as company domain
                    c.domain = ""
                    c.save()
                    comp_domain_nullified += 1

            # For orphan_candidates (companies with only personal messages + no threads) that weren't covered above
            orphan_deleted = 0
            for ent in orphan_candidates:
                c = ent["company"]
                if Company.objects.filter(id=c.id).exists():
                    orphan_deleted += Company.objects.filter(id=c.id).delete()[0]

            print(f"\nApplied changes:")
            print(f" - DomainToCompany rows deleted: {dtc_deleted}")
            print(f" - Company rows deleted: {comp_deleted + orphan_deleted}")
            print(f" - Company domains cleared (kept company rows): {comp_domain_nullified}")

    except Exception as e:
        print(f"Error applying changes: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Cleanup personal-domain artifacts")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--yes", action="store_true", help="Assume yes for prompts")

    args = parser.parse_args()
    run(dry_run=not args.apply, apply_changes=args.apply, assume_yes=args.yes)


if __name__ == "__main__":
    main()
