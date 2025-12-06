"""Test predict_with_fallback to verify noise override."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from parser import predict_with_fallback
from ml_subject_classifier import predict_subject_type

subject = "Deep Dive: China's Global Strategy and Power Balance"
body = "newsletter digest recommendation"
sender = "Chamath Palihapitiya <chamath@substack.com>"

print("Testing predict_with_fallback:")
print(f"Subject: {subject}")
print(f"Body: {body}")
print(f"Sender: {sender}")
print()

# First check what ML predicts
ml_result = predict_subject_type(subject, body, sender=sender)
print(f"ML prediction: {ml_result}")
print()

# Now check what predict_with_fallback returns
final_result = predict_with_fallback(predict_subject_type, subject, body, threshold=0.55, sender=sender)
print(f"predict_with_fallback result: {final_result}")
print()

if final_result.get('label') == 'noise':
    print("✅ SUCCESS: Correctly overridden to noise")
else:
    print(f"❌ FAIL: Expected 'noise' but got '{final_result.get('label')}'")
