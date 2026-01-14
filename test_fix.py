#!/usr/bin/env python3
"""Test script to verify the newsletter detection fix for rejection emails."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from parser import is_application_related

# Test with the AIG rejection email content
test_subject = 'Application to Senior Cyber Threat Intelligence Analyst position'
test_body = '''Dear Adrian We appreciate the time you took to apply for the JR2505367 Senior Cyber
Threat Intelligence Analyst position.

After a thorough review of your background, we have decided to pursue other candidates
who more closely match the job requirements.'''

print('Testing is_application_related function with AIG rejection email:')
print(f'Subject: {test_subject}')
print(f'Body snippet: {test_body[:100]}...')
print()

result = is_application_related(test_subject, test_body)
print(f'Result: {result}')
print()

if result:
    print('✅ SUCCESS! The rejection email is now detected as job-related.')
    print('   It will NOT be ignored as a newsletter.')
else:
    print('❌ FAILED! The rejection email is still not detected as job-related.')
    print('   It will be incorrectly ignored as a newsletter.')
