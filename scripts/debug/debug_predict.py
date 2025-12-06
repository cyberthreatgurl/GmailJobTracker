#!/usr/bin/env python
import os

import django

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import rule_label

from ml_subject_classifier import (
    body_vectorizer,
    model,
    predict_subject_type,
    subject_vectorizer,
)

subject = "Kelly, we have received your application for Engineering Manager"
body = "Thank you for applying. Your application will be reviewed."

print("=" * 80)
print("DEBUG: Module state")
print("=" * 80)
print(f"model is None: {model is None}")
print(f"subject_vectorizer is None: {subject_vectorizer is None}")
print(f"body_vectorizer is None: {body_vectorizer is None}")
print()

print("=" * 80)
print("Step 1: Call rule_label() directly")
print("=" * 80)
rule_result = rule_label(subject, body)
print(f"rule_result = {repr(rule_result)}")
print(f"bool(rule_result) = {bool(rule_result)}")
print()

print("=" * 80)
print("Step 2: Simulate predict_subject_type() logic")
print("=" * 80)

# Get ignore labels
ignore_labels = {"noise", "job_alert", "head_hunter"}

# Try rule-based first
rule_result = rule_label(subject, body)
print(f"After rule_label: rule_result = {repr(rule_result)}")

# If confident rule match, use it
if rule_result:
    print("✅ rule_result is truthy, should return early")
    result = {
        "label": rule_result,
        "confidence": 0.95,
        "ignore": rule_result in ignore_labels,
        "method": "rules",
    }
    print(f"Early return result: {result}")
else:
    print("❌ rule_result is falsy, continuing to ML")

print()

print("=" * 80)
print("Step 3: Call actual predict_subject_type()")
print("=" * 80)
full_result = predict_subject_type(subject, body)
print(f"Result: {full_result}")
