import os
import sys
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Company, ThreadTracking, Message

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("companies", nargs="+", help="Company names (partial or exact)")
args = parser.parse_args()

for name in args.companies:
    print("\n=== Company lookup:", name, "===")
    comp_qs = Company.objects.filter(name__icontains=name)
    if not comp_qs.exists():
        print(" No Company record found (case-insensitive contains)")
        continue
    for comp in comp_qs:
        print("\n-- Company:", comp.id, comp.name)
        tts = ThreadTracking.objects.filter(company=comp, interview_date__isnull=False)
        print(" ThreadTracking interviews count:", tts.count())
        for tt in tts:
            print(
                "  TT id:",
                tt.id,
                "thread_id:",
                tt.thread_id,
                "sent_date:",
                tt.sent_date,
                "interview_date:",
                tt.interview_date,
                "ml_label:",
                tt.ml_label,
                "ml_confidence:",
                tt.ml_confidence,
                "status:",
                tt.status,
                "company_source:",
                tt.company_source,
            )
            msgs = Message.objects.filter(thread_id=tt.thread_id).order_by("timestamp")
            print("   Messages in thread:", msgs.count())
            for m in msgs:
                subj = (m.subject or "").replace("\n", " ").strip()[:200]
                print(
                    "    MSG:", m.id, m.msg_id, m.timestamp, m.ml_label, m.sender, subj
                )

print("\nDone")
