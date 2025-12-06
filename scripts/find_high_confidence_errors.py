"""
Script to find high-confidence predictions that are likely wrong for manual relabeling.
- Outputs a CSV with msg_id, subject, body, predicted_label, confidence, human_label (if any)
- Only includes messages with confidence > 0.8 and (predicted != human label)
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import pandas as pd

from tracker.models import Message

THRESHOLD = 0.8
OUTPUT = "high_confidence_errors.csv"

# Query all messages with ML label and confidence
qs = Message.objects.filter(ml_label__isnull=False, confidence__gte=THRESHOLD)

rows = []
for msg in qs:
    # If human label exists and differs from ML label, flag for review
    # (Assume human label is stored in reviewed=True and ml_label != None)
    if (
        msg.reviewed
        and msg.ml_label
        and hasattr(msg, "human_label")
        and msg.human_label
    ):
        if msg.ml_label != msg.human_label:
            rows.append(
                [
                    msg.msg_id,
                    msg.subject,
                    msg.body,
                    msg.ml_label,
                    msg.confidence,
                    msg.human_label,
                ]
            )
    # If not reviewed, just output for manual review
    elif not msg.reviewed:
        rows.append(
            [msg.msg_id, msg.subject, msg.body, msg.ml_label, msg.confidence, ""]
        )

if rows:
    df = pd.DataFrame(
        rows,
        columns=[
            "msg_id",
            "subject",
            "body",
            "predicted_label",
            "confidence",
            "human_label",
        ],
    )
    df.to_csv(OUTPUT, index=False)
    print(f"Wrote {len(df)} high-confidence error candidates to {OUTPUT}")
else:
    print("No high-confidence error candidates found.")
