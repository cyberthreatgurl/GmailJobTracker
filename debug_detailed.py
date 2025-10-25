#!/usr/bin/env python
"""Debug parse_subject with detailed output."""

import os
import django
import re

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import DOMAIN_TO_COMPANY, KNOWN_COMPANIES, company_data

subject = "Application to Northrop Grumman"
sender = "careers@northropgrumman.com"
sender_domain = "northropgrumman.com"

print(f"Subject: {subject}")
print(f"Sender: {sender}")
print(f"Domain: {sender_domain}")
print()

# Simulate parse_subject logic step by step
subject_clean = subject.strip()
subject_clean = re.sub(
    r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject_clean, flags=re.IGNORECASE
).strip()
subj_lower = subject_clean.lower()
domain_lower = sender_domain.lower() if sender_domain else None

print(f"Cleaned subject: '{subject_clean}'")
print(f"Lowercase subject: '{subj_lower}'")
print(f"Domain lowercase: '{domain_lower}'")
print()

# Check known companies
print("Checking known companies...")
print(f"KNOWN_COMPANIES: {list(KNOWN_COMPANIES)[:5]}")  # show first 5
sorted_companies = sorted(KNOWN_COMPANIES, key=len, reverse=True)
found_known = None
for known in sorted_companies:
    if known in subj_lower:
        print(f"  ✅ Found '{known}' in subject")
        # Find original casing
        for orig in company_data.get("known", []):
            if orig.lower() == known:
                found_known = orig
                print(f"  ✅ Original casing: '{orig}'")
                break
        break
    else:
        if "northrop" in known:
            print(f"  ❌ '{known}' NOT in '{subj_lower}'")

if not found_known:
    print("  ❌ No known company matched")
print()

# Check domain mapping
print("Checking domain mapping...")
print(
    f"Domain '{domain_lower}' in DOMAIN_TO_COMPANY: {domain_lower in DOMAIN_TO_COMPANY}"
)
if domain_lower in DOMAIN_TO_COMPANY:
    print(f"  ✅ Mapped to: '{DOMAIN_TO_COMPANY[domain_lower]}'")
else:
    print("  ❌ No domain mapping found")
print()

# Check regex patterns
print("Checking regex patterns...")
patterns = [
    (r"application (?:to|for|with)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
]
for pat, flags in patterns:
    match = re.search(pat, subject_clean, flags)
    if match:
        print(f"  ✅ Pattern matched: {pat}")
        print(f"  ✅ Extracted: '{match.group(1)}'")
    else:
        print(f"  ❌ Pattern did not match: {pat}")
