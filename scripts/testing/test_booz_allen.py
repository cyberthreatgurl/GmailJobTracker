#!/usr/bin/env python
"""Test Booz Allen application email classification."""

import os
import sys

import django

# Add parent directory to path
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject

subject = "Thank you for applying"
body = """Thanks Adrian Shaw!

We just received your application for the OT Cybersecurity Analyst position. We're currently reviewing your skills and experience, and if you're a good fit, we will be in touch.

Meanwhile, you can track the status of your application here. We also encourage you to connect with us on LinkedIn, Twitter, Facebook and Instagram.

We're looking forward to changing the world with you.

Booz Allen Talent Acquisition"""

sender = "workday@bah.com"

result = parse_subject(
    subject=subject, body=body, sender=sender, sender_domain="bah.com"
)

print("\n" + "=" * 70)
print("BOOZ ALLEN APPLICATION EMAIL TEST")
print("=" * 70)
print(f"Subject: {subject}")
print(f"Sender: {sender}")
print("\nClassification Result:")
print(f"  Label: {result.get('label')}")
print(f"  Confidence: {result.get('confidence')}")
print(f"  Company: {result.get('company')}")
print(f"  Method: {result.get('method')}")
print(f"  Ignore: {result.get('ignore')}")
print("=" * 70)

# Verify expectations
if result.get("label") == "application" or result.get("label") == "job_application":
    print("✅ SUCCESS: Correctly labeled as application!")
else:
    print(f"❌ FAIL: Expected 'application', got '{result.get('label')}'")

if result.get("label") != "head_hunter":
    print("✅ SUCCESS: Not mislabeled as headhunter!")
else:
    print("❌ FAIL: Still being labeled as headhunter")
