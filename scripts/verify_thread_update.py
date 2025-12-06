import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

from tracker.models import Message, ThreadTracking

THREAD_ID = '19aa1ce0506cf65b'

def main():
    msg = Message.objects.filter(thread_id=THREAD_ID).first()
    tt = ThreadTracking.objects.filter(thread_id=THREAD_ID).first()
    print('Message id:', getattr(msg, 'id', None))
    print('Message company:', getattr(msg.company, 'name', None))
    print('Message company_source:', getattr(msg, 'company_source', None))
    print('ThreadTracking id:', getattr(tt, 'id', None))
    print('ThreadTracking company:', getattr(tt.company, 'name', None))
    print('ThreadTracking rejection_date:', getattr(tt, 'rejection_date', None))
    print('ThreadTracking interview_date:', getattr(tt, 'interview_date', None))

if __name__ == '__main__':
    main()
