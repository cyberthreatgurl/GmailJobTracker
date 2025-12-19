#!/usr/bin/env python
"""Test company extraction from Hampton email."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django

django.setup()

from parser import parse_subject
import re

# Simulate the Hampton email
subject = "Thank You for Applying at Hampton, VA"
body = """Dear Kelly, Thank you very much for your recent application to Millennium Corporation.  Your submission will be reviewed by our recruiting staff, and we will contact you soon, should we feel that your background meets our current needs. Sincerely, Millennium Corporation This is an automated email response. Please do not reply. © Millennium Corporation; 1400 Crystal Dr Ste 400; Arlington, VA 22202-4156; USA"""
sender = '"Millennium Corporation @ icims" <millgroupinc+autoreply@talent.icims.com>'
sender_domain = "talent.icims.com"

print("=" * 80)
print("TESTING HAMPTON EMAIL PARSING")
print("=" * 80)
print(f"\nSubject: {subject}")
print(f"Sender: {sender}")
print(f"Domain: {sender_domain}")

# Test parse_subject
result = parse_subject(subject, body, sender=sender, sender_domain=sender_domain)

print("\n" + "=" * 80)
print("PARSE_SUBJECT RESULT")
print("=" * 80)
print(f"Company: {result.get('company', 'NOT EXTRACTED')}")
print(f"Job Title: {result.get('job_title', 'N/A')}")
print(f"Label: {result.get('label', 'N/A')}")

# Manual test of sender parsing
print("\n" + "=" * 80)
print("MANUAL SENDER PARSING TEST")
print("=" * 80)

from email.utils import parseaddr

display_name, email = parseaddr(sender)
print(f"Display Name: '{display_name}'")
print(f"Email: '{email}'")

# Clean display name
cleaned = re.sub(
    r"\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring)\b",
    "",
    display_name,
    flags=re.I,
).strip()
print(f"Cleaned (removing ATS terms): '{cleaned}'")

# Check if @ icims should be removed
cleaned_at = re.sub(r"\s*@\s*icims\s*$", "", cleaned, flags=re.I).strip()
print(f"After removing @ icims: '{cleaned_at}'")
