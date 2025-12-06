"""Test rule_label function to verify noise pattern matching."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from parser import rule_label
import re

subject = "Deep Dive: China's Global Strategy and Power Balance"
body = "newsletter digest recommendation"

print("Testing rule_label function:")
print(f"Subject: {subject}")
print(f"Body: {body}")
print()

result = rule_label(subject, body)
print(f"rule_label result: {result}")
print()

# Test individual patterns
text = f"{subject} {body}"
print(f"Combined text: {text}")
print()

newsletter_pattern = re.compile(r'\bnewsletter\b', re.I)
digest_pattern = re.compile(r'\bdigest\b', re.I)
referral_pattern = re.compile(r'(\breferral\b| \breferred\b|\brefer\b|\brecommendation\b|\brecommended\b|introduction\b|\sconnect\syou\swith\b |\bconnecting\syou\swith\b)', re.I)

print(f"Newsletter match: {bool(newsletter_pattern.search(text))} -> {newsletter_pattern.search(text).group(0) if newsletter_pattern.search(text) else None}")
print(f"Digest match: {bool(digest_pattern.search(text))} -> {digest_pattern.search(text).group(0) if digest_pattern.search(text) else None}")
print(f"Referral match: {bool(referral_pattern.search(text))} -> {referral_pattern.search(text).group(0) if referral_pattern.search(text) else None}")
