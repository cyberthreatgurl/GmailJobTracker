#!/usr/bin/env python
"""Fix Data Intelligence message company association."""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, Company, ThreadTracking


def main():
    # Find the message
    msg = Message.objects.filter(
        subject='Application Received Confirmation',
        sender__icontains='applicantstack'
    ).order_by('-timestamp').first()
    
    if not msg:
        print('Message not found')
        return
    
    print(f'Found message:')
    print(f'  msg_id: {msg.msg_id}')
    print(f'  current company: {msg.company}')
    print(f'  company_id: {msg.company_id}')
    
    # Find Data Intelligence company
    data_intel = Company.objects.filter(id=264).first()
    print(f'\nData Intelligence company: {data_intel}')
    
    if not data_intel:
        print('Data Intelligence company not found!')
        return
    
    # Update message
    msg.company = data_intel
    msg.company_source = 'ats_display_name'
    msg.save()
    print(f'\n✅ Updated message company to: {msg.company}')
    
    # Update ThreadTracking if exists
    tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
    if tt:
        tt.company = data_intel
        tt.save()
        print(f'✅ Updated ThreadTracking company to: {tt.company}')
    else:
        print('No ThreadTracking found for this thread')


if __name__ == "__main__":
    main()
