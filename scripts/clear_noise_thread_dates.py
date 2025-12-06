import json
from pathlib import Path
import sys

sys.path.insert(0, r'C:\Users\kaver\code\GmailJobTracker')
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from tracker.models import ThreadTracking


def main():
    ts = __import__('datetime').datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    p = Path('scripts')
    p.mkdir(exist_ok=True)
    # Find ThreadTracking rows marked as noise with non-null dates
    from django.db.models import Q
    q = ThreadTracking.objects.filter(ml_label='noise').filter(Q(rejection_date__isnull=False) | Q(interview_date__isnull=False))
    rows = []
    for tt in q.order_by('id'):
        rows.append({
            'id': tt.id,
            'thread_id': tt.thread_id,
            'company_id': tt.company.id if tt.company_id else None,
            'company_name': getattr(tt.company, 'name', None),
            'sent_date': tt.sent_date.isoformat() if tt.sent_date else None,
            'rejection_date': tt.rejection_date.isoformat() if tt.rejection_date else None,
            'interview_date': tt.interview_date.isoformat() if tt.interview_date else None,
            'ml_label': tt.ml_label,
            'ml_confidence': float(tt.ml_confidence or 0),
        })

    if not rows:
        print('No noise ThreadTracking rows with dates to clear found.')
        return

    backup = p / f'clear_noise_thread_dates_backup_{ts}.json'
    with backup.open('w', encoding='utf-8') as fh:
        json.dump({'ts': ts, 'rows': rows}, fh, indent=2)
    print(f'Wrote backup to: {backup}')

    # Apply changes
    changed = 0
    for tt in ThreadTracking.objects.filter(id__in=[r['id'] for r in rows]):
        if tt.rejection_date is not None or tt.interview_date is not None:
            tt.rejection_date = None
            tt.interview_date = None
            tt.save()
            changed += 1

    print(f'Cleared dates on {changed} ThreadTracking row(s).')


if __name__ == '__main__':
    main()
