#!/usr/bin/env python
"""
Check if the bad "rejection" company can be safely deleted
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message, Application

# Get the bad company
bad = Company.objects.get(id=35)

# Check references
msgs = Message.objects.filter(company=bad).count()
apps = ThreadTracking.objects.filter(company=bad).count()

print(f'Company "{bad.name}" (ID {bad.id}):')
print(f'  - {msgs} messages')
print(f'  - {apps} applications')
print()

if msgs == 0 and apps == 0:
    print('✅ Safe to delete!')
    delete = input('Delete this company record? (y/n): ')
    if delete.lower() == 'y':
        bad.delete()
        print(f'Deleted company "{bad.name}" (ID {bad.id})')
else:
    print('⚠️  Still has references - do not delete')

