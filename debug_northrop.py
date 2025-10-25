#!/usr/bin/env python
"""Debug parse_subject flow."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject, DOMAIN_TO_COMPANY, KNOWN_COMPANIES

print(
    "DOMAIN_TO_COMPANY:",
    {k: v for k, v in DOMAIN_TO_COMPANY.items() if "northrop" in k.lower()},
)
print("KNOWN_COMPANIES:", [k for k in KNOWN_COMPANIES if "northrop" in k])
print()

subject = "Application to Northrop Grumman"
sender = "careers@northropgrumman.com"
domain = "northropgrumman.com"

print(f"Test: {subject}")
print(f"Sender: {sender}")
print(f"Domain: {domain}")
print()

result = parse_subject(subject=subject, sender=sender, sender_domain=domain)
print("Result:", result)
print(f"Company: '{result.get('company')}'")
print(f"Label: {result.get('label')}")
