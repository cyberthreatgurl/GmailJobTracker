#!/usr/bin/env python3
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from ml_subject_classifier import predict_subject_type
from parser import rule_label

subject = "NSA Employment Processing Update"
sender = "NSA Talent Acquistion <uwe-svc-hr-talent@uwe.nsa.gov>"

print("Testing rules-only via parser.rule_label...")
print("rule_label:", rule_label(subject, ""))

print("\nTesting predict_subject_type (rules-first)...")
res = predict_subject_type(subject, body="", sender=sender)
print(res)
