
import os
import django
import sys

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message, ThreadTracking

# Find the company Red River
try:
    company = Company.objects.get(name="Red River")
    print(f"Found Company: {company.name} (ID: {company.id})")
except Company.DoesNotExist:
    print("Company 'Red River' not found.")
    sys.exit(1)

# Find messages for this company
messages = Message.objects.filter(company=company)
print(f"\nFound {messages.count()} messages for {company.name}:")

for msg in messages:
    print(f"- Message ID: {msg.id}")
    print(f"  Subject: {msg.subject}")
    print(f"  Thread ID: {msg.thread_id}")
    print(f"  ML Label: {msg.ml_label}")
    print(f"  Date: {msg.timestamp}")

    # Check for linked ThreadTracking (Application)
    try:
        thread = ThreadTracking.objects.get(thread_id=msg.thread_id)
        print(f"  -> Found ThreadTracking (ID: {thread.id})")
        print(f"     Company: {thread.company.name} (ID: {thread.company.id})")
        print(f"     ML Label: {thread.ml_label}")
    except ThreadTracking.DoesNotExist:
        print(f"  -> NO ThreadTracking found for thread_id: {msg.thread_id}")

