#!/usr/bin/env python
"""Test classification with various email types."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import rule_label

test_cases = [
    {
        "name": "Application Confirmation",
        "subject": "Thank you for applying to Software Engineer",
        "body": "We have received your application and will review it carefully.",
        "expected": "job_application"
    },
    {
        "name": "Interview Invite",
        "subject": "Next steps for Software Engineer position",
        "body": "We would like to schedule an interview with you. Please select a time that works.",
        "expected": "interview_invite"
    },
    {
        "name": "Rejection (soft)",
        "subject": "Update on your application",
        "body": "Thank you for applying. Unfortunately, we have decided to move forward with other candidates.",
        "expected": "rejected"
    },
    {
        "name": "Rejection (after interview)",
        "subject": "RE: Software Engineer Position",
        "body": "We appreciated the time you spent interviewing. We regret to inform you that we have selected another candidate.",
        "expected": "rejected"
    },
    {
        "name": "Offer",
        "subject": "Offer for Software Engineer Position",
        "body": "Congratulations! We are pleased to extend an offer for the Software Engineer position.",
        "expected": "offer"
    },
    {
        "name": "Application with 'next steps' (should be application, not interview)",
        "subject": "We have received your application",
        "body": "Thank you for applying. What's next? Your application will be reviewed by our team.",
        "expected": "job_application"
    },
    {
        "name": "Rejection with 'received application' (should be rejection, not application)",
        "subject": "Update on your application",
        "body": "We received your application for the role. Unfortunately, the position has been closed.",
        "expected": "rejected"
    }
]

print("=" * 80)
print("EMAIL CLASSIFICATION TEST RESULTS")
print("=" * 80)

passed = 0
failed = 0

for test in test_cases:
    result = rule_label(test["subject"], test["body"])
    status = "✓ PASS" if result == test["expected"] else "✗ FAIL"
    
    if result == test["expected"]:
        passed += 1
    else:
        failed += 1
    
    print(f"\n{status} - {test['name']}")
    print(f"  Expected: {test['expected']}")
    print(f"  Got:      {result}")
    if result != test["expected"]:
        print(f"  Subject:  {test['subject'][:60]}")
        print(f"  Body:     {test['body'][:60]}...")

print(f"\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
print("=" * 80)
