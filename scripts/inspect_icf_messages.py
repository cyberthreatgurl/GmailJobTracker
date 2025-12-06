import os
import sys
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

from tracker.models import Company, ThreadTracking, Message

CID = 134

comp = Company.objects.filter(id=CID).first()
if not comp:
    print(f"No company with id={CID}")
    sys.exit(0)

print(f"Company: {comp.id} {comp.name}")

msgs = Message.objects.filter(company_id=CID).order_by('timestamp')
print(f"Total messages for company {CID}: {msgs.count()}")
for m in msgs:
    subj = (m.subject or '').replace('\n',' ').strip()[:200]
    print(f"MSG: {m.id} thread_id:{m.thread_id} ts:{m.timestamp} ml_label:{m.ml_label} ml_conf:{getattr(m,'ml_confidence',None)} sender:{m.sender} subj:{subj}")

tts = ThreadTracking.objects.filter(company_id=CID).order_by('sent_date')
print(f"ThreadTracking rows for company {CID}: {tts.count()}")
for tt in tts:
    print(f"TT: id:{tt.id} thread_id:{tt.thread_id} sent:{tt.sent_date} interview_date:{tt.interview_date} ml_label:{tt.ml_label} ml_conf:{getattr(tt,'ml_confidence',None)} status:{tt.status} source:{tt.company_source}")
    ms = Message.objects.filter(thread_id=tt.thread_id).order_by('timestamp')
    print(f"  messages_in_thread: {ms.count()}")
    for m in ms:
        subj = (m.subject or '').replace('\n',' ').strip()[:200]
        print(f"   MSG: {m.id} {m.timestamp} {m.ml_label} {m.sender} {subj}")

print("Done")
