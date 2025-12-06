#!/usr/bin/env python
"""
Find companies with names that look like labels instead of real company names
"""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from pathlib import Path

from tracker.models import Company, Message

# Load message labels from patterns.json to avoid hardcoding
patterns_path = Path(__file__).parent / "json" / "patterns.json"
try:
    with open(patterns_path) as f:
        patterns_data = json.load(f)
    # Get all message label keys plus common variations
    message_label_keys = set(patterns_data.get("message_labels", {}).keys())
    # Add common variations that might appear as company names
    invalid_company_names = message_label_keys | {
        "rejection",
        "interview",
        "application",
        "other",
        "unknown",
    }
except Exception as e:
    print(f"Warning: Could not load patterns.json: {e}")
    # Fallback to minimal set
    invalid_company_names = {
        "rejection",
        "rejected",
        "interview",
        "interview_invite",
        "job_application",
        "application",
        "noise",
        "job_alert",
        "head_hunter",
        "referral",
        "ghosted",
        "follow_up",
        "response",
        "offer",
        "other",
        "unknown",
    }

print("Looking for companies with invalid names (labels)...")
print()

bad_companies = Company.objects.filter(name__in=invalid_company_names)

if bad_companies.exists():
    print(f"⚠️  Found {bad_companies.count()} companies with label-like names:")
    print()
    for company in bad_companies:
        msg_count = Message.objects.filter(company=company).count()
        print(f"  - ID {company.id}: '{company.name}' ({msg_count} messages)")
    print()
    print("These should be cleaned up!")
else:
    print("✅ No companies with invalid label names found!")
