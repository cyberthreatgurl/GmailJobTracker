"""Test Indeed application confirmation email classification."""

import os
import sys

# Bootstrap Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django

django.setup()

from ml_subject_classifier import predict_subject_type, rule_label

# Real email data from the Indeed EML
subject = "Indeed Application: Cyber Security Engineer"
body = """Your application has been submitted. Good luck!
If you notice an error in your application, please Contact Indeed

The following items were sent to Millennium Corporation. Good luck!
Resume
Cover letter"""

sender = "Indeed Apply <indeedapply@indeed.com>"

print("=" * 60)
print("INDEED APPLICATION CONFIRMATION TEST")
print("=" * 60)

# Test rule-based classification directly
rule_result = rule_label(subject, body)
print(f"\n✅ Rule classification:")
print(f"   Result: {rule_result}")

# Test full prediction pipeline
result = predict_subject_type(subject, body, threshold=0.55, sender=sender)
print(f"\n✅ Full classification:")
print(f"   Label: {result['label']}")
print(f"   Confidence: {result['confidence']:.4f}")
print(f"   Method: {result.get('method', 'N/A')}")

# Validation
expected = "job_application"  # or 'application'
actual = result["label"]

if actual not in ("job_application", "application"):
    print(f"\n❌ FAILURE: Expected '{expected}' or 'application', got '{actual}'")
    print("\nThis indicates the pattern matching is not working correctly.")
    print("Check patterns.json 'application' patterns and priority order.")
else:
    print(f"\n✅ SUCCESS: Classified as {actual} (application confirmation)")
