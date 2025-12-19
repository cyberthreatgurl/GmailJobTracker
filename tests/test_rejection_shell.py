#!/usr/bin/env python3
"""Test the rejection pattern fix - Django shell version."""

# Test data from the LinkedIn rejection email
subject = (
    "Your application to Information System Security Officer at Wireless Research Group"
)
sender = "LinkedIn <jobs-noreply@linkedin.com>"
body = """Your update from Wireless Research Group

This email was intended for Kelly Shaw, DSc
"""

from parser import parse_subject

print("=" * 80)
print("Testing LinkedIn Rejection Email")
print("=" * 80)
result = parse_subject(subject, body, sender=sender, sender_domain="linkedin.com")
print(f"\nSubject: {subject}")
print(f"Sender: {sender}")
print(f"Label: {result.get('label')}")
print(f"Confidence: {result.get('confidence')}")
print(f"Company: {result.get('company')}")

if result.get("label") == "rejection":
    print("\n✅ SUCCESS: Email correctly identified as rejection")
else:
    print(
        f"\n❌ FAILED: Email labeled as '{result.get('label')}' instead of 'rejection'"
    )
