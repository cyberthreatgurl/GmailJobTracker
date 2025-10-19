"""
remove_noise_companies.py

Removes all Company, Application, and Message records where all associated messages are labeled as 'noise', and deletes those companies from the database.

Usage:
    python remove_noise_companies.py

This script should be run from the project root with the Django environment loaded.
"""

import os
import django
import sys

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Application, Message
from django.db import transaction


def main():
    print("Scanning for companies with only noise-labeled messages...")
    noise_label = "noise"
    total_companies = 0
    total_deleted = 0
    total_messages = 0
    total_apps = 0

    # Find companies where all messages are labeled as noise
    companies = Company.objects.all()
    for company in companies:
        msgs = Message.objects.filter(company=company)
        if not msgs.exists():
            continue
        total_companies += 1
        # If all messages for this company are noise
        if all(m.ml_label == noise_label for m in msgs):
            with transaction.atomic():
                msg_count = msgs.count()
                app_count = Application.objects.filter(company=company).count()
                # Delete messages
                msgs.delete()
                # Delete applications
                Application.objects.filter(company=company).delete()
                # Delete company
                company.delete()
                print(
                    f"Deleted company '{company.name}' with {msg_count} messages and {app_count} applications (all noise)"
                )
                total_deleted += 1
                total_messages += msg_count
                total_apps += app_count

    print(
        f"\nDone. Deleted {total_deleted} companies, {total_messages} messages, {total_apps} applications."
    )


if __name__ == "__main__":
    main()
