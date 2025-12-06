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
from django.db import transaction

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true', help='Apply changes (default dry-run)')
parser.add_argument('companies', nargs='+', help='Company names (partial match)')
args = parser.parse_args()

DRY_RUN = not args.apply

now_ts = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
backup_path = os.path.join('scripts', f'clear_interview_backup_{now_ts}.json')

rows = []
for name in args.companies:
    qs = Company.objects.filter(name__icontains=name)
    if not qs.exists():
        print(f'No company matching: {name}')
        continue
    for comp in qs:
        tts = ThreadTracking.objects.filter(company=comp, interview_date__isnull=False)
        for tt in tts:
            msgs = Message.objects.filter(thread_id=tt.thread_id).order_by('timestamp')
            rows.append({
                'company_search': name,
                'company_id': comp.id,
                'company_name': comp.name,
                'threadtracking': {
                    'id': tt.id,
                    'thread_id': tt.thread_id,
                    'sent_date': str(tt.sent_date) if tt.sent_date else None,
                    'interview_date': str(tt.interview_date) if tt.interview_date else None,
                    'ml_label': tt.ml_label,
                    'ml_confidence': tt.ml_confidence,
                    'status': tt.status,
                    'company_source': tt.company_source,
                },
                'messages': [
                    {
                        'id': m.id,
                        'msg_id': m.msg_id,
                        'timestamp': str(m.timestamp),
                        'ml_label': m.ml_label,
                        'subject': (m.subject or '')[:300]
                    }
                    for m in msgs
                ]
            })

with open(backup_path, 'w', encoding='utf-8') as f:
    json.dump(rows, f, indent=2)

print(f'Backup written with {len(rows)} entries to {backup_path}')

if DRY_RUN:
    print('Dry run mode - no changes made. Rerun with --apply to clear interview_date.')
    sys.exit(0)

changed = 0
with transaction.atomic():
    for ent in rows:
        tid = ent['threadtracking']['thread_id']
        tt = ThreadTracking.objects.filter(thread_id=tid).first()
        if tt and tt.interview_date is not None:
            tt.interview_date = None
            tt.save()
            changed += 1

print(f'Cleared interview_date on {changed} ThreadTracking rows')
