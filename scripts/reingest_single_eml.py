import sys
import os
from pathlib import Path

sys.path.insert(0, r'C:\Users\kaver\code\GmailJobTracker')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

from email.utils import parseaddr
from parser import parse_raw_message, predict_with_fallback, extract_status_dates, _map_company_by_domain
from ml_subject_classifier import predict_subject_type
from tracker.models import Message, ThreadTracking, Company


EML_PATH = r'C:\Users\kaver\OneDrive\Downloads\DHS Cybersecurity Service Application Status Update for the Cybersecurity Research and Development - Leadership position (Vacancy #12404802).eml'


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


def main():
    if not Path(EML_PATH).exists():
        print('EML file not found:', EML_PATH)
        return
    raw = open(EML_PATH, 'rb').read()
    try:
        raw_text = raw.decode('utf-8', errors='ignore')
    except Exception:
        raw_text = str(raw)

    parsed = parse_raw_message(raw_text)
    subject = parsed.get('subject', '')
    body = parsed.get('body', '')
    sender = parsed.get('sender') or ''
    sender_addr = parseaddr(sender)[1] if sender else ''

    # Try to find existing Message by Message-ID if present
    import re
    m = re.search(r'^Message-ID:\s*<([^>]+)>', raw_text, re.I | re.M)
    msg_id = m.group(1) if m else None
    msg = None
    if msg_id:
        msg = Message.objects.filter(msg_id=msg_id).first()
    if not msg:
        # fallback to subject-based find
        msg = Message.objects.filter(subject__icontains=subject[:40]).order_by('-timestamp').first()

    print('Found Message:', getattr(msg, 'id', None), getattr(msg, 'msg_id', None))

    # Predict label
    ml = predict_with_fallback(predict_subject_type, subject or '', body or '', threshold=0.6, sender=sender_addr or '')
    print('Prediction:', ml)
    ml_label = ml.get('label') if ml else None
    ml_conf = float(ml.get('confidence', 0.0) if ml else 0.0)

    # Update or create Message record
    if not msg:
        # create minimal Message record if none exists
        msg = Message.objects.create(
            msg_id=msg_id or f'generated-{os.urandom(6).hex()}',
            thread_id=parsed.get('thread_id') or f't-{os.urandom(4).hex()}',
            subject=subject,
            sender=sender,
            body=body,
            body_html=parsed.get('body_html', ''),
            timestamp=parsed.get('timestamp') or None,
            ml_label=ml_label,
            confidence=ml_conf,
        )
        print('Created Message id=', msg.id)
    else:
        msg.ml_label = ml_label
        msg.confidence = ml_conf
        msg.save()
        print('Updated Message id=', msg.id)

    # Try map company by sender domain or parser extraction (use parser mapping loader)
    sender_domain = (parsed.get('sender_domain') or (sender_addr.split('@')[-1] if '@' in sender_addr else '')).lower()
    company_name = None
    try:
        if sender_domain:
            company_name = _map_company_by_domain(sender_domain)
    except Exception:
        company_name = None

    # Also check parsed subject/company
    parsed_company = parsed.get('company') or ''
    if parsed_company and not company_name:
        company_name = parsed_company

    if company_name:
        company_obj, _ = Company.objects.get_or_create(name=company_name, defaults={
            'first_contact': msg.timestamp or None,
            'last_contact': msg.timestamp or None,
        })
        msg.company = company_obj
        msg.company_source = 'domain_mapping' if sender_domain else 'subject_parse'
        msg.save()
        print('Assigned company ->', company_obj.name)

    # Update ThreadTracking if exists
    if msg.thread_id:
        tt = ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if tt:
            tt.ml_label = ml_label
            tt.ml_confidence = ml_conf
            # extract explicit dates and fallback
            status_dates = None
            try:
                status_dates = extract_status_dates(body or '', msg.timestamp)
            except Exception:
                status_dates = {}
            rej = to_date(status_dates.get('rejection_date')) if status_dates else None
            intr = to_date(status_dates.get('interview_date')) if status_dates else None
            if not rej and ml_label in ('rejected', 'rejection'):
                rej = msg.timestamp.date() if msg.timestamp else None
            if not intr and ml_label and 'interview' in str(ml_label).lower() and ml_conf >= 0.7:
                intr = msg.timestamp.date() if msg.timestamp else None
            if rej and not tt.rejection_date:
                tt.rejection_date = rej
            if intr and not tt.interview_date:
                tt.interview_date = intr
            if company_name and tt.company.name != company_name:
                try:
                    tt.company = company_obj
                except Exception:
                    pass
            tt.save()
            print('Updated ThreadTracking id=', tt.id, 'company=', getattr(tt.company, 'name', None), 'rejection_date=', tt.rejection_date, 'interview_date=', tt.interview_date)
        else:
            print('No ThreadTracking found for thread_id=', msg.thread_id)

    print('Done')


if __name__ == '__main__':
    main()
