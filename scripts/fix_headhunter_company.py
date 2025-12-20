#!/usr/bin/env python
"""
Fix headhunter messages that have a Company object named "HeadHunter".

This script:
1. Finds all Company objects with name="HeadHunter" (case-insensitive)
2. Finds all Messages/ThreadTracking linked to these companies
3. Sets their company to None
4. Deletes the "HeadHunter" Company objects

Run: python scripts/fix_headhunter_company.py
"""

import os
import sys
import django

# Setup Django
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message, ThreadTracking
from django.db.models import Q, Count


def main():
    print("=" * 80)
    print("Headhunter Company Cleanup")
    print("=" * 80)

    # Find Company objects with name="HeadHunter" or similar variations
    headhunter_companies = Company.objects.filter(
        Q(name__iexact="HeadHunter")
        | Q(name__iexact="Head Hunter")
        | Q(name__iexact="Headhunter")
        | Q(status="headhunter")
    ).annotate(message_count=Count("message"), thread_count=Count("threadtracking"))

    # Also check for Messages with ml_label="head_hunter" but company is NOT None
    headhunter_messages_with_company = Message.objects.filter(
        ml_label="head_hunter", company__isnull=False
    ).select_related("company")

    if (
        not headhunter_companies.exists()
        and not headhunter_messages_with_company.exists()
    ):
        print("✅ No HeadHunter company objects found - database is clean!")
        print("✅ No head_hunter messages with companies found - database is clean!")
        return

    if headhunter_companies.exists():
        print(
            f"\n📊 Found {headhunter_companies.count()} headhunter company objects:\n"
        )

        for company in headhunter_companies:
            print(f"  • {company.name} (ID: {company.id})")
            print(f"    - Status: {company.status}")
            print(f"    - Domain: {company.domain or '(none)'}")
            print(f"    - Messages: {company.message_count}")
            print(f"    - Threads: {company.thread_count}")
            print()

    if headhunter_messages_with_company.exists():
        print(
            f"\n📊 Found {headhunter_messages_with_company.count()} head_hunter messages with companies:\n"
        )
        company_counts = {}
        for msg in headhunter_messages_with_company[:20]:  # Show first 20
            company_name = msg.company.name if msg.company else "None"
            company_counts[company_name] = company_counts.get(company_name, 0) + 1

        for company_name, count in sorted(company_counts.items(), key=lambda x: -x[1]):
            print(f"  • {company_name}: {count} messages")

        if headhunter_messages_with_company.count() > 20:
            print(f"  ... and {headhunter_messages_with_company.count() - 20} more")
        print()

    # Ask for confirmation
    response = input("🔧 Clean up these headhunter records? (yes/no): ")
    if response.lower() not in ["yes", "y"]:
        print("❌ Aborted - no changes made")
        return

    # Track stats
    messages_updated = 0
    threads_updated = 0
    threads_deleted = 0
    companies_deleted = 0

    # First, fix all head_hunter messages that have companies
    print(f"\n🔄 Clearing companies from head_hunter messages...")
    hh_msg_count = Message.objects.filter(
        ml_label="head_hunter", company__isnull=False
    ).update(company=None, company_source="headhunter_domain")
    messages_updated += hh_msg_count
    print(f"  ✓ Updated {hh_msg_count} head_hunter messages")

    # Delete ThreadTracking for headhunters (they shouldn't have threads)
    print(f"\n🔄 Deleting ThreadTracking records for headhunters...")
    hh_threads = ThreadTracking.objects.filter(
        Q(ml_label="head_hunter")
        | Q(company__status="headhunter")
        | Q(company__name__iexact="HeadHunter")
        | Q(company__name__iexact="Head Hunter")
        | Q(company__name__iexact="Headhunter")
    )
    threads_deleted = hh_threads.count()
    hh_threads.delete()
    print(f"  ✓ Deleted {threads_deleted} headhunter threads")

    # Now handle Company objects
    for company in headhunter_companies:
        print(f"\n🔄 Processing: {company.name}")

        # Update any remaining Messages to remove company link
        msg_count = Message.objects.filter(company=company).update(
            company=None, company_source="headhunter_domain"
        )
        messages_updated += msg_count
        if msg_count > 0:
            print(f"  ✓ Updated {msg_count} messages")

        # Update any remaining ThreadTracking to remove company link
        thread_count = ThreadTracking.objects.filter(company=company).update(
            company=None, company_source="headhunter_domain"
        )
        threads_updated += thread_count
        if thread_count > 0:
            print(f"  ✓ Updated {thread_count} threads")

        # Delete the Company object
        company.delete()
        companies_deleted += 1
        print(f"  ✓ Deleted company: {company.name}")

    print("\n" + "=" * 80)
    print("✅ Cleanup Complete!")
    print("=" * 80)
    print(f"  • Companies deleted: {companies_deleted}")
    print(f"  • Messages updated: {messages_updated}")
    print(f"  • Threads updated: {threads_updated}")
    print(f"  • Threads deleted: {threads_deleted}")
    print()
    print("💡 Next steps:")
    print(
        "   1. Check your dashboard - headhunter messages should now show 'No Company'"
    )
    print(
        "   2. If you see any more issues, re-ingest: python manage.py ingest_gmail --days 7"
    )
    print(
        "   3. The parser.py code has been fixed to prevent this from happening again"
    )
    print()


if __name__ == "__main__":
    main()
