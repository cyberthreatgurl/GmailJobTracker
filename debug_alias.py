#!/usr/bin/env python
"""Debug alias lookup."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import company_data, ATS_DOMAINS

sender = "ngc@myworkday.com"
domain = "myworkday.com"

print(f"Sender: {sender}")
print(f"Domain: {domain}")
print(f"Domain in ATS_DOMAINS: {domain in ATS_DOMAINS}")
print()

# Extract prefix
sender_prefix = sender.split("@")[0].strip().lower()
print(f"Sender prefix: '{sender_prefix}'")
print()

# Check aliases
aliases = company_data.get("aliases", {})
print("Aliases (first 5):")
for k, v in list(aliases.items())[:5]:
    print(f"  '{k}' -> '{v}'")
print()

aliases_lower = {k.lower(): v for k, v in aliases.items()}
print(f"Lowercase aliases: {list(aliases_lower.keys())}")
print()

print(f"'{sender_prefix}' in aliases_lower: {sender_prefix in aliases_lower}")
if sender_prefix in aliases_lower:
    print(f"Maps to: '{aliases_lower[sender_prefix]}'")
