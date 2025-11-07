#!/usr/bin/env python3
"""Quick test for subdomain-aware domain mapping.

Runs parse_subject on a synthetic NSA subdomain email to confirm mapping.
"""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from parser import parse_subject

subject = "NSA Employment Processing Update"
sender = "NSA Talent Acquisition <uwe-svc-hr-talent@uwe.nsa.gov>"
sender_domain = "uwe.nsa.gov"

res = parse_subject(subject, body="", sender=sender, sender_domain=sender_domain)
print(res)
