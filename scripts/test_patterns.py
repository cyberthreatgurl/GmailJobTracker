#!/usr/bin/env python
"""Test application pattern matching"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from parser import is_application_related

test_subjects = [
    "Application Received - Thank You",
    "We continue to evaluate your job application",
    "SEI Application Received",
    "CrowdStrike Job Application Confirmation",
    "Your Parsons Job Application for: [not available]",
    "We've received your Target job application",
    "Adrian, Thank you from Elastic",
    "Thanks for joining our Talent Pool - Nozomi Networks",
    "Trellix career opportunity update",
    "Venture Global LNG Interview Availability",
]

print("Testing application pattern matching:\n")
for subject in test_subjects:
    result = is_application_related(subject, "")
    status = "✓ MATCH" if result else "✗ NO MATCH"
    print(f"{status:12} | {subject}")
