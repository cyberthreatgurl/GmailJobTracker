#!/usr/bin/env python3
"""Test script to verify 'pru' alias matching for Prudential"""

import sys
import os
import django

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

# Set DEBUG mode
os.environ['DEBUG'] = '1'

# Import parser components
from parser import parse_subject, _domain_mapper

# Force reload to get latest companies.json
_domain_mapper.reload_if_needed()

# Test data matching the Prudential email
test_subject = "Application Submitted for Cybersecurity Engineer"
test_sender = "Workday <pru@myworkday.com>"
test_body = """Thank you for your interest in the position of Specialist, Cyber Security (LBPS) at Prudential.

We have received your application and will review it carefully."""

print("=" * 80)
print("Testing Prudential alias matching")
print("=" * 80)
print(f"Subject: {test_subject}")
print(f"Sender: {test_sender}")
print(f"Body snippet: {test_body[:100]}...")
print("=" * 80)

# Call parse_subject
result = parse_subject(
    subject=test_subject,
    body=test_body,
    sender=test_sender,
    sender_domain="myworkday.com"
)

print("=" * 80)
print(f"RESULT: company='{result.get('company', 'N/A')}'")
print(f"        company_source='{result.get('company_source', 'N/A')}'")
print(f"        job_title='{result.get('job_title', 'N/A')}'")
print(f"        label='{result.get('label', 'N/A')}'")
print("=" * 80)

# Verify the alias exists
aliases = _domain_mapper.company_data.get("aliases", {})
print(f"\nTotal aliases loaded: {len(aliases)}")
print(f"'pru' in aliases: {'pru' in aliases}")
if 'pru' in aliases:
    print(f"'pru' maps to: {aliases['pru']}")

if result.get('company') == 'Prudential':
    print("\n✅ SUCCESS: Company correctly extracted as 'Prudential'")
    sys.exit(0)
else:
    print(f"\n❌ FAILED: Expected 'Prudential', got '{result.get('company', 'N/A')}'")
    sys.exit(1)
