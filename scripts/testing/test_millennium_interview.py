"""Test Millennium Corporation interview email classification and extraction."""

import os
import sys

# Bootstrap Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django

django.setup()

import parser  # noqa: F401 - local parser module, not stdlib
from parser import parse_subject, predict_with_fallback
from ml_subject_classifier import predict_subject_type

# Real email data from the EML
subject = "Response Requested - Cyber Security Engineer - Millennium Corporation"
body = """Kelly,
 
Thank you for expressing interest in our Cyber Security Engineer position supporting Langley AFB. We would like to press forward with a call to further discuss the opportunity with you.
 
When able, please provide me with your availability for next week. 
 
I look forward to your response!"""

sender = "Nandi Hopps <millgroupinc+email+lta-a258e23f1d@talent.icims.com>"
sender_domain = "talent.icims.com"

print("=" * 60)
print("MILLENNIUM CORPORATION INTERVIEW EMAIL TEST")
print("=" * 60)

# Test rule-based classification first
result = predict_with_fallback(
    predict_subject_type, subject, body, threshold=0.55, sender=sender
)
print(f"\n✅ Classification:")
print(f"   Label: {result['label']}")
print(f"   Confidence: {result['confidence']:.4f}")

# Test company extraction
parsed = parse_subject(subject, body=body, sender=sender, sender_domain=sender_domain)
print(f"\n✅ Company extraction:")
print(f"   Company: {parsed['company']}")
print(f"   Job title: {parsed['job_title']}")

# Validation
assert (
    result["label"] == "interview_invite"
), f"Expected 'interview_invite', got '{result['label']}'"
assert (
    parsed["company"] == "Millennium Corporation"
), f"Expected 'Millennium Corporation', got '{parsed['company']}'"

print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED!")
print("=" * 60)
