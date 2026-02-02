#!/usr/bin/env python
"""Find and fix ThreadTracking records missing rejection dates.

This script:
1. Finds rejection/cancelled messages
2. Checks if the company's ThreadTracking has rejection_date set
3. Optionally populates the rejection_date based on the message timestamp
"""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message, ThreadTracking


def find_missing_rejection_dates(fix=False):
    """Find ThreadTracking records missing rejection dates for companies with rejection messages."""
    
    # Find all rejection/cancelled messages
    rejection_messages = Message.objects.filter(
        ml_label__in=['rejection', 'cancelled'],
        company__isnull=False
    ).select_related('company').order_by('company__name', 'timestamp')
    
    print(f"Total rejection/cancelled messages: {rejection_messages.count()}")
    print("-" * 80)
    
    found_issues = []
    
    for msg in rejection_messages:
        company = msg.company
        
        # Find ThreadTracking for this company
        tt = ThreadTracking.objects.filter(company=company).order_by('sent_date').first()
        
        if not tt:
            # No ThreadTracking for this company - could be a separate issue
            continue
        
        # Check if rejection_date is missing
        if tt.rejection_date is None:
            rejection_date = msg.timestamp.date() if msg.timestamp else None
            found_issues.append({
                'company': company,
                'company_id': company.id,
                'company_name': company.name,
                'tt_thread_id': tt.thread_id,
                'msg_thread_id': msg.thread_id,
                'msg_label': msg.ml_label,
                'msg_subject': msg.subject[:50] if msg.subject else '',
                'rejection_date': rejection_date,
                'is_cancelled': msg.ml_label == 'cancelled',
            })
    
    if not found_issues:
        print("\n✅ No ThreadTracking records found with missing rejection dates.")
        return
    
    # Deduplicate by company (keep earliest rejection date)
    seen_companies = {}
    for issue in found_issues:
        cid = issue['company_id']
        if cid not in seen_companies:
            seen_companies[cid] = issue
        elif issue['rejection_date'] and (
            not seen_companies[cid]['rejection_date'] or 
            issue['rejection_date'] < seen_companies[cid]['rejection_date']
        ):
            seen_companies[cid] = issue
    
    unique_issues = list(seen_companies.values())
    
    print(f"\n⚠️  Found {len(unique_issues)} ThreadTracking records with missing rejection dates:\n")
    
    for i, issue in enumerate(unique_issues, 1):
        print(f"{i}. {issue['company_name']} (id={issue['company_id']})")
        print(f"   Rejection Date: {issue['rejection_date']}")
        print(f"   Cancelled: {issue['is_cancelled']}")
        print(f"   Message: {issue['msg_subject']}...")
        print(f"   Message thread_id: {issue['msg_thread_id'][:30]}...")
        print(f"   TT thread_id: {issue['tt_thread_id'][:30]}...")
        print()
    
    if not fix:
        print("-" * 80)
        print("Run with --fix to update the rejection dates.")
        return unique_issues
    
    # Fix the issues
    print("-" * 80)
    print("Fixing rejection dates...")
    
    for issue in unique_issues:
        tt = ThreadTracking.objects.filter(company_id=issue['company_id']).order_by('sent_date').first()
        if tt:
            tt.rejection_date = issue['rejection_date']
            if issue['is_cancelled']:
                tt.cancelled = True
            tt.save()
            cancelled_str = " (cancelled=True)" if issue['is_cancelled'] else ""
            print(f"  ✅ {issue['company_name']}: rejection_date = {issue['rejection_date']}{cancelled_str}")
    
    print(f"\n✅ Fixed {len(unique_issues)} ThreadTracking records.")
    return unique_issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Find and fix ThreadTracking records missing rejection dates")
    parser.add_argument('--fix', action='store_true', help='Update the rejection dates')
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes (default)')
    args = parser.parse_args()
    
    fix = args.fix and not args.dry_run
    
    if fix:
        print("Mode: FIX (will update database)")
    else:
        print("Mode: DRY-RUN (preview only)")
    print()
    
    find_missing_rejection_dates(fix=fix)


if __name__ == "__main__":
    main()
