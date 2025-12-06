import os
import sys
import json

sys.path.insert(0, r'C:\Users\kaver\code\GmailJobTracker')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

from tracker.models import Message

def show(sender, limit=10):
    qs = Message.objects.filter(sender__icontains=sender).order_by('-timestamp')[:limit]
    out = []
    for m in qs:
        out.append({
            'id': m.id,
            'subject': (m.subject or '')[:200],
            'ml_label': m.ml_label,
            'confidence': float(m.confidence or 0),
            'sender': m.sender,
            'thread_id': m.thread_id,
            'company': getattr(m.company, 'name', None),
            'timestamp': m.timestamp.isoformat() if m.timestamp else None,
        })
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('sender')
    p.add_argument('--limit', type=int, default=10)
    args = p.parse_args()
    show(args.sender, args.limit)
