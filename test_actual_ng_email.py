#!/usr/bin/env python
"""Test actual Northrop Grumman email extraction."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject

# Actual email from attachment
subject = (
    "Status Update - R10202035 Principal Classified Cybersecurity Analyst - TS/SCI"
)
sender = "ngc@myworkday.com"
domain = "myworkday.com"
body = """Dear Adrian,

Thank you for your interest in a career with Northrop Grumman. After careful review, we have decided to move forward with other candidates for the position of Principal Classified Cybersecurity Analyst - TS/SCI.

New positions are posted daily on our careers website. We encourage you to apply for relevant openings that align with your experience and career goals.

We recognize the effort it takes to explore new possibilities and appreciate the time you invested in applying to this position.

Kind Regards,

Northrop Grumman Talent Acquisition Team

Ref ID: JA07"""

print(f"Subject: {subject}")
print(f"Sender: {sender}")
print(f"Domain: {domain}")
print()

result = parse_subject(subject=subject, body=body, sender=sender, sender_domain=domain)

print("Result:")
print(f"  Company: '{result.get('company')}'")
print(f"  Job Title: '{result.get('job_title')}'")
print(f"  Label: {result.get('label')}")
print(f"  Confidence: {result.get('confidence')}")
print(f"  Ignore: {result.get('ignore')}")
print()

if result.get("company") == "Northrop Grumman":
    print("✅ SUCCESS: Northrop Grumman extracted correctly!")
else:
    print(f"❌ FAIL: Expected 'Northrop Grumman', got '{result.get('company')}'")
