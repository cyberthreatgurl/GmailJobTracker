"""Test Millennium Hampton VA application email."""

import os
import sys

# Bootstrap Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django

django.setup()

from parser import parse_subject

# Real email data from the log
subject = "Thank You for Applying at Hampton, VA"
body = """Thank you for applying..."""
sender = '"Millennium Corporation @ icims" <millgroupinc+autoreply@talent.icims.com>'
sender_domain = "talent.icims.com"

print("=" * 60)
print("MILLENNIUM HAMPTON VA APPLICATION TEST")
print("=" * 60)

# Test company extraction
parsed = parse_subject(subject, body=body, sender=sender, sender_domain=sender_domain)
print(f"\n✅ Company extraction:")
print(f"   Company: {parsed['company']}")
print(f"   Label: {parsed['label']}")

# Validation
expected = "Millennium Corporation"
actual = parsed["company"]

if actual != expected:
    print(f"\n❌ FAILURE: Expected '{expected}', got '{actual}'")
    print("\nIssue: Subject pattern 'at Hampton' should not override ATS display name.")
else:
    print(f"\n✅ SUCCESS: Correctly extracted company from ATS display name")
    print(f"   (Avoided false match on location 'Hampton, VA')")
