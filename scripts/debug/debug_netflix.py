#!/usr/bin/env python
"""Debug Netflix classification step by step."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import re
from parser import predict_with_fallback, rule_label, should_ignore

from ml_subject_classifier import predict_subject_type

subject = "Kelly, we have received your application for Engineering Manager, Attack Emulation Team"
body = """Dear Kelly, 

Thank you for applying for the role of Engineering Manager, Attack Emulation Team at Netflix! It's exciting to see your interest in joining the Dream Team and contributing to our mission to entertain the world. Your qualifications and experiences will be reviewed to determine if there's a mutual fit. 

What's next? If there's interest in discussing the position further, you will be contacted about potential next steps. Thank you again for your time and enthusiasm. Expect to hear from us soon. 

Sincerely, 
The Netflix Talent Acquisition Team"""

print("=== STEP 1: Rule-based classification ===")
rule_result = rule_label(subject, body)
print(f"Rule label: {rule_result}")

print("\n=== STEP 2: ML classification (with fallback) ===")
ml_result = predict_with_fallback(predict_subject_type, subject, body, threshold=0.55)
print(f"ML result: {ml_result}")

print("\n=== STEP 3: Should ignore check ===")
ignore_result = should_ignore(subject, body)
print(f"Should ignore: {ignore_result}")

print("\n=== STEP 4: Check RESUME_NOISE_PATTERNS ===")
from parser import RESUME_NOISE_PATTERNS

matches = [p for p in RESUME_NOISE_PATTERNS if re.search(p, subject, re.I)]
print(f"Matching RESUME_NOISE_PATTERNS: {matches}")
