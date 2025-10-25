#!/usr/bin/env python
"""Direct inline test without imports."""

import os
import django
import sys

# Force reimport
if "parser" in sys.modules:
    del sys.modules["parser"]

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

# Now import
from parser import parse_subject, DEBUG

print(f"DEBUG value: {DEBUG}")
print(f"parse_subject function: {parse_subject}")
print()

subject = (
    "Status Update - R10202035 Principal Classified Cybersecurity Analyst - TS/SCI"
)
sender = "ngc@myworkday.com"
domain = "myworkday.com"
body = "Thank you for your interest in a career with Northrop Grumman..."

result = parse_subject(subject=subject, body=body, sender=sender, sender_domain=domain)
print(f"\nResult company: '{result.get('company')}'")
