import sys, os
sys.path.insert(0, r'C:\Users\kaver\code\GmailJobTracker')
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from email.parser import BytesParser
from email import policy
from email.utils import parsedate_to_datetime, parseaddr

from parser import parse_raw_message, predict_with_fallback, extract_status_dates
from ml_subject_classifier import predict_subject_type
from tracker.models import Message, ThreadTracking

EML_PATH = r'd:\Users\kaver\Downloads\Your Application with ICF.eml'

raw = open(EML_PATH, 'rb').read()
raw_text = raw.decode('utf-8', errors='ignore')
parsed = parse_raw_message(raw_text) if parse_raw_message else {}
subject = parsed.get('subject', '')
body = parsed.get('body', '')
# Try to extract Message-ID
import re
m = re.search(r'^Message-ID:\s*<([^>]+)>', raw_text, re.I | re.M)
if m:
    msg_id = m.group(1)
else:
    # fallback: try to find msg by subject and timestamp
    msg_id = None

# Find message record
if msg_id:
    msg = Message.objects.filter(msg_id=msg_id).first()
else:
    # try to find by subject and approximate timestamp
    msg = Message.objects.filter(subject__icontains=subject[:40]).order_by('-timestamp').first()

if not msg:
    print('Message record not found; aborting')
    sys.exit(1)

print(f'Found Message id={msg.id} msg_id={msg.msg_id} thread_id={msg.thread_id}')

# Determine sender for ML helper
sender = parsed.get('sender') or ''
from_addr = parseaddr(sender)[1] if sender else ''

ml = predict_with_fallback(predict_subject_type, subject or '', body or '', threshold=0.6, sender=from_addr or '')
print('Prediction:', ml)
ml_label = ml.get('label') if ml else None
ml_conf = float(ml.get('confidence', 0.0) if ml else 0.0)

# Update Message
msg.ml_label = ml_label
msg.confidence = ml_conf
msg.save()
print(f'Updated Message {msg.id}: ml_label={msg.ml_label} confidence={msg.confidence}')

# Update ThreadTracking if exists
if msg.thread_id:
    tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
    if not tt:
        print('No ThreadTracking found for thread_id=', msg.thread_id)
    else:
        # Extract explicit dates
        status_dates = None
        try:
            if extract_status_dates:
                # Try parse_raw_message body if available
                body_for_classify = parsed.get('body', '')
                # use message timestamp as dt
                dt = msg.timestamp if msg.timestamp else None
                status_dates = extract_status_dates(body_for_classify or '', dt)
        except Exception as e:
            print('extract_status_dates error:', e)
            status_dates = None

        def to_date(val):
            from datetime import datetime, date
            if val is None:
                return None
            if isinstance(val, date):
                return val
            if isinstance(val, datetime):
                return val.date()
            if isinstance(val, str) and val.strip():
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
                    try:
                        return datetime.strptime(val.strip(), fmt).date()
                    except Exception:
                        continue
            return None

        rej_date = to_date(status_dates.get('rejection_date')) if status_dates else None
        int_date = to_date(status_dates.get('interview_date')) if status_dates else None

        # Fallback from ML labels
        try:
            if ml_label:
                ml_l = str(ml_label).lower()
                if not rej_date and ml_l in ('rejected', 'rejection'):
                    rej_date = msg.timestamp.date() if msg.timestamp else None
                if not int_date and 'interview' in ml_l and ml_conf >= 0.7:
                    int_date = msg.timestamp.date() if msg.timestamp else None
        except Exception:
            pass

        # Apply updates
        tt.ml_label = ml_label
        tt.ml_confidence = ml_conf
        if ml_label:
            tt.status = ml_label
        if rej_date and (not tt.rejection_date):
            tt.rejection_date = rej_date
        if int_date and (not tt.interview_date):
            tt.interview_date = int_date
        tt.save()
        print(f'Updated ThreadTracking {tt.id}: ml_label={tt.ml_label} ml_confidence={tt.ml_confidence} status={tt.status} rejection_date={tt.rejection_date} interview_date={tt.interview_date}')
else:
    print('Message has no thread_id; nothing to update')

print('Done')
