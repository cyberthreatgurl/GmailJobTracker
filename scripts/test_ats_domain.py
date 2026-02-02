#!/usr/bin/env python
"""Test ATS domain logic."""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import update_company_domain_and_ats, get_or_create_company_iexact, _is_ats_domain
from tracker.models import Company
from django.utils import timezone


def main():
    test_company_name = 'Test ATS Company XYZ'
    sender_domain = 'applicantstack.com'
    now = timezone.now()

    print(f'Testing ATS domain logic:')
    print(f'  Company: {test_company_name}')
    print(f'  Sender domain: {sender_domain}')
    print(f'  Is ATS domain: {_is_ats_domain(sender_domain)}')

    # Clean up any existing test company
    test_company = Company.objects.filter(name=test_company_name).first()
    if test_company:
        print(f'\nExisting test company found, deleting...')
        test_company.delete()

    # Create test company
    test_company, created = get_or_create_company_iexact(
        test_company_name,
        defaults={'confidence': 0.9, 'first_contact': now, 'last_contact': now}
    )
    print(f'\nCreated company: {test_company.name} (created={created})')
    print(f'  domain: {test_company.domain}')
    print(f'  ats: {test_company.ats}')

    # Call update_company_domain_and_ats
    result = update_company_domain_and_ats(test_company, sender_domain, test_company_name)
    print(f'\nAfter update_company_domain_and_ats (changed={result}):')
    print(f'  domain: {test_company.domain}')
    print(f'  ats: {test_company.ats}')

    # Verify the ats field is set correctly
    if test_company.ats == sender_domain:
        print('\n✅ SUCCESS: ATS domain correctly set!')
    else:
        print(f'\n❌ FAILURE: ATS domain not set correctly. Expected "{sender_domain}", got "{test_company.ats}"')

    # Clean up
    test_company.delete()
    print('\nTest company deleted.')


if __name__ == "__main__":
    main()
