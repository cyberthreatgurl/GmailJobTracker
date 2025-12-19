#!/usr/bin/env python
"""Debug where Hampton is being extracted from."""
import os

os.environ["DEBUG"] = "1"  # Enable debug mode
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django

django.setup()

# Patch parse_subject to add tracing
import parser as parser_module

original_parse_subject = parser_module.parse_subject


def traced_parse_subject(subject, body="", sender=None, sender_domain=None):
    print("\n### TRACING parse_subject ###")
    print(f"Inputs:")
    print(f"  subject: {subject}")
    print(f"  sender: {sender}")
    print(f"  sender_domain: {sender_domain}")

    result = original_parse_subject(subject, body, sender, sender_domain)

    print(f"\nResult:")
    print(f"  company: {result.get('company', 'NOT SET')}")
    print("### END TRACE ###\n")

    return result


# Monkey patch
parser_module.parse_subject = traced_parse_subject

# Now test
from parser import parse_subject

subject = "Thank You for Applying at Hampton, VA"
body = "Dear Kelly, Thank you very much for your recent application to Millennium Corporation."
sender = '"Millennium Corporation @ icims" <millgroupinc+autoreply@talent.icims.com>'
sender_domain = "talent.icims.com"

result = parse_subject(subject, body, sender=sender, sender_domain=sender_domain)
print("\n" + "=" * 80)
print(f"FINAL: Company extracted = '{result.get('company', 'NONE')}'")
print("=" * 80)
