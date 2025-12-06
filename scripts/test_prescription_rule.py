#!/usr/bin/env python
"""
Test why prescription messages aren't matching the noise rule.
"""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django
django.setup()

from ml_subject_classifier import predict_subject_type, rule_label
import json
from pathlib import Path

# Test data
subject = "Your prescription is ready"
body = "Your Walmart Pharmacy prescription is ready for pickup."
sender = '"Walmart.com" <help@walmart.com>'

print("=" * 80)
print("TESTING PRESCRIPTION CLASSIFICATION")
print("=" * 80)

# Load patterns
patterns_path = Path("json/patterns.json")
with open(patterns_path, 'r', encoding='utf-8') as f:
    patterns = json.load(f)

print("\nNoise patterns from patterns.json:")
for pattern in patterns.get("message_labels", {}).get("noise", []):
    print(f"  - {pattern}")

# Test rule matching
print("\n" + "=" * 80)
print("TESTING RULE_LABEL FUNCTION")
print("=" * 80)
rule_result = rule_label(subject, body)
print(f"\nrule_label('{subject}', body) = {rule_result}")

# Test full prediction
print("\n" + "=" * 80)
print("TESTING PREDICT_SUBJECT_TYPE")
print("=" * 80)
result = predict_subject_type(subject, body, threshold=0.55, sender=sender)
print(f"\nResult:")
print(f"  Label: {result['label']}")
print(f"  Confidence: {result['confidence']:.4f}")
print(f"  Ignore: {result.get('ignore', False)}")
print(f"  Method: {result.get('method', 'unknown')}")

# Check if pattern matches manually
import re
text = f"{subject} {body}".lower()
print("\n" + "=" * 80)
print("MANUAL PATTERN TESTING")
print("=" * 80)
print(f"\nCombined text (lowercased): '{text}'")

test_patterns = [
    r"\bprescription\b",
    r"\\bprescription\\b",
    r"\nprescription\b",
]

for pat in test_patterns:
    try:
        regex = re.compile(pat, re.IGNORECASE)
        match = regex.search(text)
        print(f"\nPattern: {repr(pat)}")
        print(f"  Matches: {bool(match)}")
        if match:
            print(f"  Matched text: '{match.group(0)}'")
    except re.error as e:
        print(f"\nPattern: {repr(pat)}")
        print(f"  ERROR: {e}")
