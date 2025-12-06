#!/usr/bin/env python3
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()
from tracker.models import Company, Message, ThreadTracking

def info():
    for cid in (134, 645):
        c = Company.objects.filter(id=cid).first()
        if c:
            msg_count = Message.objects.filter(company=c).count()
            tt_count = ThreadTracking.objects.filter(company=c).count()
            print(f"Company id={cid} name='{c.name}' msgs={msg_count} tt={tt_count}")
        else:
            print(f"Company id={cid} not found")

if __name__ == '__main__':
    info()
