#!/usr/bin/env python
"""
Cleanup script: fix mis-attributed companies for ATS/iCIMS messages where the
company was parsed from the subject instead of the sender display name.

Usage:
  # Dry run (default)
  python scripts/cleanup_icims_sender_company.py

  # Apply changes
  APPLY=1 python scripts/cleanup_icims_sender_company.py

What it does:
- Scans messages whose sender domain is a subdomain of known ATS domains
  (icims.com, workday.com, greenhouse-mail.io, lever.co, indeed.com)
- For each message whose company_source is 'subject_parse', tries to
  re-derive company from sender display name (stripping '@ icims' suffix)
- If different and valid, updates message.company and company_source='ats_sender'

Safety:
- Dry-run by default, prints proposed changes
- Set APPLY=1 to write changes
"""
import os
import re
from email.utils import parseaddr

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.db.models import Q
from tracker.models import Message, Company

ATS_ROOTS = [
    "icims.com",
    "workday.com",
    "greenhouse-mail.io",
    "lever.co",
    "indeed.com",
]

APPLY = os.getenv("APPLY", "0").strip() in {"1", "true", "True", "yes", "y"}


def is_ats_subdomain(domain: str) -> bool:
    if not domain:
        return False
    domain = domain.lower()
    for root in ATS_ROOTS:
        if domain == root or domain.endswith("." + root):
            return True
    return False


def clean_sender_display_name(sender: str) -> str:
    display_name, _ = parseaddr(sender or "")
    cleaned = re.sub(
        r"\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring)\b",
        "",
        display_name,
        flags=re.I,
    ).strip()
    # Remove ATS platform suffixes (e.g., "@ icims", "@ Workday", etc.)
    cleaned = re.sub(r"\s*@\s*(icims|workday|greenhouse|lever|indeed)\s*$", "", cleaned, flags=re.I).strip()
    return cleaned


def get_or_create_company(name: str) -> Company | None:
    if not name:
        return None
    obj, _ = Company.objects.get_or_create(name=name)
    return obj


print("=" * 80)
print("ICIMS/ATS CLEANUP (Dry Run)" if not APPLY else "ICIMS/ATS CLEANUP (Apply)")
print("=" * 80)

qs = Message.objects.exclude(company__isnull=True)
qs = qs.filter(company_source__in=["subject_parse", "", None])

# Heuristic: likely ATS messages
qs = qs.filter(
    Q(sender__icontains="@icims.") |
    Q(sender__icontains="@workday.") |
    Q(sender__icontains="@greenhouse-") |
    Q(sender__icontains="@lever.") |
    Q(sender__icontains="@indeed.")
).order_by("-timestamp")

proposed = []
for msg in qs:
    # Extract domain
    sender = msg.sender or ""
    email_part = parseaddr(sender)[1]
    domain = email_part.split("@", 1)[1] if "@" in email_part else ""
    if not is_ats_subdomain(domain):
        continue

    new_name = clean_sender_display_name(sender)
    if not new_name or new_name == (msg.company.name if msg.company else ""):
        continue

    proposed.append((msg, new_name))

print(f"Found {len(proposed)} messages with a better company candidate from sender.")

for i, (msg, new_name) in enumerate(proposed, 1):
    print(f"\n{i}. {msg.timestamp:%Y-%m-%d %H:%M} | current='{msg.company.name}', new='{new_name}'")
    print(f"   Subject: {msg.subject[:90]}")
    print(f"   Sender:  {msg.sender}")

if APPLY and proposed:
    print("\nApplying changes...")
    changed = 0
    for msg, new_name in proposed:
        new_company = get_or_create_company(new_name)
        if not new_company:
            continue
        msg.company = new_company
        msg.company_source = "ats_sender"
        msg.save(update_fields=["company", "company_source"])
        changed += 1
    print(f"\n✓ Updated {changed} messages.")
else:
    print("\nDry run only. Set APPLY=1 to apply changes.")
