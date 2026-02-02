#!/usr/bin/env python
"""Find and fix companies with missing ATS domains.

This script:
1. Finds companies with empty `ats` field
2. Checks if they have messages from known ATS domains
3. Optionally populates the `ats` field based on the sender domain
"""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message
from parser import _is_ats_domain


def find_missing_ats_domains(fix=False):
    """Find companies with missing ATS domains that have messages from ATS domains."""
    
    # Find companies with empty ats field
    companies_no_ats = Company.objects.filter(ats__isnull=True) | Company.objects.filter(ats='')
    
    print(f"Companies with empty ATS field: {companies_no_ats.count()}")
    print("-" * 80)
    
    found_issues = []
    
    for company in companies_no_ats:
        # Get all messages for this company
        messages = Message.objects.filter(company=company).order_by('-timestamp')
        
        if not messages.exists():
            continue
        
        # Check each message for ATS domain
        for msg in messages:
            # Extract domain from sender
            sender = msg.sender or ""
            import re
            match = re.search(r'@([\w.-]+)', sender)
            if not match:
                continue
            
            sender_domain = match.group(1).lower()
            
            if _is_ats_domain(sender_domain):
                found_issues.append({
                    'company': company,
                    'company_id': company.id,
                    'company_name': company.name,
                    'ats_domain': sender_domain,
                    'msg_subject': msg.subject[:50] if msg.subject else '',
                    'msg_label': msg.ml_label,
                    'sender': sender,
                })
                break  # Only need one ATS message per company
    
    if not found_issues:
        print("\n✅ No companies found with missing ATS domains that have ATS messages.")
        return
    
    print(f"\n⚠️  Found {len(found_issues)} companies with missing ATS domains:\n")
    
    for i, issue in enumerate(found_issues, 1):
        print(f"{i}. {issue['company_name']} (id={issue['company_id']})")
        print(f"   ATS Domain: {issue['ats_domain']}")
        print(f"   Message: {issue['msg_subject']}...")
        print(f"   Sender: {issue['sender']}")
        print(f"   Label: {issue['msg_label']}")
        print()
    
    if not fix:
        print("-" * 80)
        print("Run with --fix to update the ATS fields.")
        return found_issues
    
    # Fix the issues
    print("-" * 80)
    print("Fixing ATS fields...")
    
    for issue in found_issues:
        company = issue['company']
        company.ats = issue['ats_domain']
        company.save()
        print(f"  ✅ {issue['company_name']}: ats = {issue['ats_domain']}")
    
    print(f"\n✅ Fixed {len(found_issues)} companies.")
    return found_issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Find and fix companies with missing ATS domains")
    parser.add_argument('--fix', action='store_true', help='Update the ATS fields')
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes (default)')
    args = parser.parse_args()
    
    fix = args.fix and not args.dry_run
    
    if fix:
        print("Mode: FIX (will update database)")
    else:
        print("Mode: DRY-RUN (preview only)")
    print()
    
    find_missing_ats_domains(fix=fix)


if __name__ == "__main__":
    main()
