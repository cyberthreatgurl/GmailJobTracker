#!/usr/bin/env python
"""Debug parse_subject step by step."""

import os
import re

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from email.utils import parseaddr
from parser import ATS_DOMAINS, company_data

subject = (
    "Status Update - R10202035 Principal Classified Cybersecurity Analyst - TS/SCI"
)
sender = "ngc@myworkday.com"
sender_domain = "myworkday.com"

print(f"Subject: {subject}")
print(f"Sender: {sender}")
print(f"Domain: {sender_domain}")
print()

subject_clean = subject.strip()
subject_clean = re.sub(
    r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject_clean, flags=re.IGNORECASE
).strip()
subj_lower = subject_clean.lower()
domain_lower = sender_domain.lower() if sender_domain else None

print(f"Cleaned subject: {subject_clean}")
print(f"Domain lowercase: {domain_lower}")
print(f"Domain in ATS_DOMAINS: {domain_lower in ATS_DOMAINS}")
print()

company = None

# ATS check
if not company and domain_lower in ATS_DOMAINS and sender:
    print("Checking ATS domain...")
    if "@" in sender:
        sender_prefix = sender.split("@")[0].strip().lower()
        print(f"  Sender prefix: '{sender_prefix}'")

        aliases_lower = {
            k.lower(): v for k, v in company_data.get("aliases", {}).items()
        }
        print(f"  Checking if '{sender_prefix}' in aliases...")
        if sender_prefix in aliases_lower:
            company = aliases_lower[sender_prefix]
            print(f"  ✅ Found in aliases: '{company}'")
        else:
            print(f"  ❌ NOT found in aliases")

    if not company:
        print("  Trying display name fallback...")
        display_name, _ = parseaddr(sender)
        print(f"  Display name: '{display_name}'")

print()
print(f"Final company after ATS check: '{company}'")
