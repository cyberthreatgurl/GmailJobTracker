#!/usr/bin/env python
"""Test classification of Netflix email."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject

subject = "Kelly, we have received your application for Engineering Manager, Attack Emulation Team"
sender = "Careers Netflix <careers@jobs.netflix.com>"
sender_domain = "jobs.netflix.com"
body = """Dear Kelly, 

Thank you for applying for the role of Engineering Manager, Attack Emulation Team at Netflix! It's exciting to see your interest in joining the Dream Team and contributing to our mission to entertain the world. Your qualifications and experiences will be reviewed to determine if there's a mutual fit. 

What's next? If there's interest in discussing the position further, you will be contacted about potential next steps. Thank you again for your time and enthusiasm. Expect to hear from us soon. 

Sincerely, 
The Netflix Talent Acquisition Team"""

result = parse_subject(subject, body, sender=sender, sender_domain=sender_domain)

print("Classification Result:")
print(f"Label: {result.get('label')}")
print(f"Confidence: {result.get('confidence')}")
print(f"Ignore: {result.get('ignore')}")
print(f"Company: {result.get('company')}")
print(f"Job Title: {result.get('job_title')}")
print(f"\nFull result:")
print(result)
