#!/usr/bin/env python
"""Test if rule_label works with the Netflix message."""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import rule_label
from ml_subject_classifier import predict_subject_type

subject = "Kelly, we have received your application for Engineering Manager"
body = "Thank you for applying. Your application will be reviewed."

print("=" * 80)
print("TEST: Simple Netflix-like message")
print("=" * 80)

print(f"\nSubject: {subject}")
print(f"Body: {body}")

print("\n--- Rule label ---")
rule_result = rule_label(subject, body)
print(f"Result: {rule_result}")

print("\n--- Full predict_subject_type ---")
ml_result = predict_subject_type(subject, body)
print(f"Result: {ml_result}")

print("\n=" * 80)
print("TEST: Actual Netflix message")
print("=" * 80)

from tracker.models import Message

msg = Message.objects.filter(
    subject__icontains="Kelly, we have received your application for Engineering Manager"
).first()

if msg:
    print(f"\nSubject: {msg.subject}")
    print(f"Body preview: {msg.body[:200] if msg.body else 'None'}...")

    print("\n--- Rule label ---")
    rule_result = rule_label(msg.subject, msg.body or "")
    print(f"Result: {rule_result}")

    print("\n--- Full predict_subject_type ---")
    ml_result = predict_subject_type(msg.subject, msg.body or "")
    print(f"Result: {ml_result}")
else:
    print("Netflix message not found in database")
