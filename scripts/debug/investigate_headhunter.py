#!/usr/bin/env python
"""Investigate head_hunter mislabeling issue."""

import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import json

from tracker.models import Message

print("=" * 80)
print("HEAD_HUNTER MISLABELING INVESTIGATION")
print("=" * 80)

# Total head_hunter messages
total_hh = Message.objects.filter(ml_label="head_hunter").count()
print(f"\nTotal messages labeled as head_hunter: {total_hh}")

# Messages with "hiring" in subject
hiring_msgs = Message.objects.filter(
    ml_label="head_hunter", subject__icontains="hiring"
)
hiring_count = hiring_msgs.count()
print(
    f"Messages with 'hiring' in subject: {hiring_count} ({hiring_count/total_hh*100:.1f}%)"
)

# Show sample subjects with "hiring"
print("\n--- Sample subjects with 'hiring' ---")
for msg in hiring_msgs.values("id", "subject", "sender", "confidence")[:15]:
    print(
        f"  ID {msg['id']:3d} | conf={msg['confidence']:.2f} | {msg['sender'][:40]:40s} | {msg['subject'][:60]}"
    )

# Check for user's own messages labeled as head_hunter
user_email = "kaver68@gmail.com"
user_hh = Message.objects.filter(
    ml_label="head_hunter", sender__icontains=user_email
).count()
print(f"\n--- User's own messages mislabeled as head_hunter: {user_hh} ---")
if user_hh > 0:
    for msg in Message.objects.filter(
        ml_label="head_hunter", sender__icontains=user_email
    ).values("id", "subject", "confidence")[:10]:
        print(
            f"  ID {msg['id']:3d} | conf={msg['confidence']:.2f} | {msg['subject'][:60]}"
        )

# Check pattern matches
print("\n--- Pattern Analysis ---")
import re

patterns_to_test = {
    "urgent\\s+hiring": r"urgent\s+hiring",
    "urgent hiring (no space req)": r"urgent.*hiring",
    "just hiring": r"\bhiring\b",
    "linkedin": r"\blinkedin\b",
}

for name, pattern in patterns_to_test.items():
    regex = re.compile(pattern, re.IGNORECASE)
    count = 0
    for msg in Message.objects.filter(ml_label="head_hunter"):
        text = f"{msg.subject or ''} {msg.body or ''}"
        if regex.search(text):
            count += 1
    print(f"  {name:30s}: {count:4d} matches")

# Load current patterns from patterns.json
print("\n--- Current head_hunter patterns in patterns.json ---")
try:
    with open("json/patterns.json", "r") as f:
        patterns_data = json.load(f)
        hh_patterns = patterns_data.get("message_labels", {}).get("head_hunter", [])
        for i, p in enumerate(hh_patterns, 1):
            print(f"  {i}. {p}")
except Exception as e:
    print(f"  Error loading patterns: {e}")

# Test current classifier on the Claroty message
print("\n--- Testing current classifier on Claroty message ---")
from ml_subject_classifier import predict_subject_type

test_cases = [
    ("LinkedIn Claroty Hiring", "Hi Noam, I am attaching my resume..."),
    ("Urgent Hiring for Cybersecurity Engineer", "We are urgently hiring..."),
    ("Software Engineer Hiring at Google", "We are hiring for..."),
]

for subject, body_snippet in test_cases:
    result = predict_subject_type(subject, body_snippet)
    print(
        f"  Subject: {subject[:50]:50s} => {result['label']:15s} (conf={result['confidence']:.2f}, method={result['method']})"
    )

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(
    f"""
The issue appears to be with the regex pattern:
  '(seeking|urgent\\sneed|urgent\\shiring|looking\\sfor|...)'

The pattern 'urgent\\shiring' should probably be 'urgent\\s+hiring' 
to require "urgent" followed by "hiring", not just any occurrence of "hiring".

However, current testing shows the message is now classified as 'noise' by ML,
suggesting the model has been retrained and these are OLD labels that haven't
been updated.

Recommended actions:
1. Fix the regex pattern to be more specific
2. Run reclassify_messages to update all historical labels
3. Consider excluding user's own messages from head_hunter classification
"""
)
