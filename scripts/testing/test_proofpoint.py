import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import parse_subject

# Proofpoint email details
subject = "Proofpoint - We have received your application."
sender = "MyWorkday@Proofpoint <donotreply@proofpoint.com>"
body = """Dear Adrian,

Thank you for applying. We have received your application and are excited that you are interested in joining the team. If you are among the qualified candidates a representative from our Human Resources team will be in contact with you soon regarding the next steps in our process.

Regards,
Proofpoint Talent Acquisition Team"""

print("Testing Proofpoint email parsing...")
print(f"Subject: {subject}")
print(f"Sender: {sender}")
print()

# Correct signature: parse_subject(subject, body="", sender=None, sender_domain=None)
result = parse_subject(
    subject, body=body, sender=sender, sender_domain="proofpoint.com"
)
print(f"Parsed company: {result['company']}")
print(f"Company source: {result.get('company_source', 'N/A')}")
print(f"Job title: {result.get('job_title', 'N/A')}")
print(f"Job ID: {result.get('job_id', 'N/A')}")
