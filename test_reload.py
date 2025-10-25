#!/usr/bin/env python
"""Test by importing parser AFTER everything is set up."""
import sys
import os

# Set up Django FIRST
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django

django.setup()

# Force reload parser module
import importlib
import parser as parser_module

importlib.reload(parser_module)

from parser import parse_subject

print("Testing with reloaded module...")

subject = (
    "Status Update - R10202035 Principal Classified Cybersecurity Analyst - TS/SCI"
)
sender = "ngc@myworkday.com"
domain = "myworkday.com"
body = "Thank you for your interest in a career with Northrop Grumman..."

result = parse_subject(subject=subject, body=body, sender=sender, sender_domain=domain)
print(f"\nResult company: '{result.get('company')}'")
