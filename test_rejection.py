#!/usr/bin/env python3
"""Test the rejection pattern fix for LinkedIn rejection emails."""

from parser import parse_subject

# Test data from the LinkedIn rejection email
subject = "Your application to Information System Security Officer at Wireless Research Group"
sender = "LinkedIn <jobs-noreply@linkedin.com>"
body = """Your update from Wireless Research Group

----------------------------------------

This email was intended for Kelly Shaw, DSc (Former CISA, ONI, NAVSEA, Naval Surface Warfare Center)
Learn why we included this
"""

# Also test the email template header content if it were in the body
body_with_header = """X-LinkedIn-Template: email_jobs_application_rejected_01
""" + body

# Parse and display results
print("=" * 80)
print("Test 1: LinkedIn Rejection Email (from subject/body)")
print("=" * 80)
result1 = parse_subject(subject, body, sender=sender, sender_domain="linkedin.com")
print(f"\nSubject: {subject}")
print(f"Sender: {sender}")
print(f"Result: {result1}")
print(f"Label: {result1.get('label')}")
print(f"Confidence: {result1.get('confidence')}")
print(f"Company: {result1.get('company')}")

print("\n" + "=" * 80)
print("Test 2: LinkedIn Rejection Email (with header template info)")
print("=" * 80)
result2 = parse_subject(subject, body_with_header, sender=sender, sender_domain="linkedin.com")
print(f"\nResult: {result2}")
print(f"Label: {result2.get('label')}")
print(f"Confidence: {result2.get('confidence')}")

print("\n" + "=" * 80)
print("Test 3: Normal Application Confirmation (should still work)")
print("=" * 80)
app_subject = "Your application to Software Engineer at Google"
app_body = "Thank you for applying to Google. We have received your application and will review it carefully."
result3 = parse_subject(app_subject, app_body, sender="Google <noreply@google.com>", sender_domain="google.com")
print(f"\nSubject: {app_subject}")
print(f"Result: {result3}")
print(f"Label: {result3.get('label')}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Test 1 - LinkedIn Rejection: {'✅ PASS' if result1.get('label') == 'rejection' else '❌ FAIL'}")
print(f"Test 2 - LinkedIn Rejection (with header): {'✅ PASS' if result2.get('label') == 'rejection' else '❌ FAIL'}")  
print(f"Test 3 - Normal Application: {'✅ PASS' if result3.get('label') == 'job_application' else '❌ FAIL'}")
