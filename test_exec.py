import os
import django

# Configure Django before importing modules that access settings/models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject  # static import so Pylance can resolve symbol

# Direct test using imported function
result = parse_subject(
    subject="Status Update - R10202035 Principal Classified Cybersecurity Analyst - TS/SCI",
    body="Thank you for your interest in a career with Northrop Grumman...",
    sender="ngc@myworkday.com",
    sender_domain="myworkday.com",
)
print(f"Company: '{result.get('company')}'")
