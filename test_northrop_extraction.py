#!/usr/bin/env python
"""Test Northrop Grumman company extraction."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject

# Test various subject line formats
test_cases = [
    {
        "subject": "Application to Northrop Grumman",
        "sender": "careers@northropgrumman.com",
        "domain": "northropgrumman.com",
    },
    {
        "subject": "Northrop Grumman: Application Received",
        "sender": "recruiting@northropgrumman.com",
        "domain": "northropgrumman.com",
    },
    {
        "subject": "Thank you for your application with Northrop Grumman",
        "sender": "noreply@northropgrumman.com",
        "domain": "northropgrumman.com",
    },
    {
        "subject": "Your application to NGC",
        "sender": "careers@northropgrumman.com",
        "domain": "northropgrumman.com",
    },
    {
        "subject": "Position at Northrop Grumman Corporation",
        "sender": "recruiting@northropgrumman.com",
        "domain": "northropgrumman.com",
    },
    {
        "subject": "Northrop Grumman Application Update",
        "sender": "careers@northropgrumman.com",
        "domain": "northropgrumman.com",
    },
]

print("Testing Northrop Grumman extraction:\n")
for i, test in enumerate(test_cases, 1):
    result = parse_subject(
        subject=test["subject"], sender=test["sender"], sender_domain=test["domain"]
    )

    company = result.get("company", "")
    print(f"Test {i}:")
    print(f"  Subject: {test['subject']}")
    print(f"  Sender: {test['sender']}")
    print(f"  Extracted Company: '{company}'")
    print(f"  Expected: 'Northrop Grumman'")
    print(f"  ✅ PASS" if company == "Northrop Grumman" else f"  ❌ FAIL")
    print()

print("\n" + "=" * 60)
print("Please paste the actual email details that failed:")
print("Subject: ")
print("Sender: ")
print("Body snippet: ")
