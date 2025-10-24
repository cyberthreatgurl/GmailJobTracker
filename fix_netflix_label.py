#!/usr/bin/env python
"""Check and re-classify Netflix message."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
from parser import parse_subject, rule_label
from ml_subject_classifier import predict_subject_type

# Find the Netflix message
msg = Message.objects.filter(
    subject__icontains="Kelly, we have received your application for Engineering Manager"
).first()

if not msg:
    print("❌ Netflix message not found in database")
    exit(1)

print("=" * 80)
print("NETFLIX MESSAGE ANALYSIS")
print("=" * 80)

print(f"\nSubject: {msg.subject}")
print(f"Current ML Label: {msg.ml_label}")
print(f"Current Confidence: {msg.confidence}")
print(f"Body exists: {bool(msg.body)}")
print(f"Body length: {len(msg.body) if msg.body else 0}")

# Test with rule-based classification
print("\n--- RULE-BASED CLASSIFICATION ---")
rule_result = rule_label(msg.subject, msg.body or "")
print(f"Rule label: {rule_result}")

# Test with full classification
print("\n--- ML CLASSIFICATION (with fallback) ---")
ml_result = predict_subject_type(msg.subject, msg.body or "")
print(f"ML result: {ml_result}")

# Test with parse_subject (full pipeline)
print("\n--- FULL PARSE_SUBJECT PIPELINE ---")
parse_result = parse_subject(
    msg.subject, msg.body or "", sender=msg.sender, sender_domain="jobs.netflix.com"
)
print(f"Parse result label: {parse_result.get('label')}")
print(f"Parse result confidence: {parse_result.get('confidence')}")
print(f"Parse result ignore: {parse_result.get('ignore')}")

# Update the message
print("\n--- UPDATING MESSAGE ---")
msg.ml_label = parse_result.get("label")
msg.confidence = parse_result.get("confidence")
msg.save()
print(f"✅ Updated message to: {msg.ml_label} ({msg.confidence:.2%})")
