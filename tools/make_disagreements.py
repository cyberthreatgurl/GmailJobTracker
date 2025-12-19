"""Produce reviewed_disagreements.csv: messages where reviewed=True and ML prediction != stored label.

This script uses the existing export logic to get the ML prediction for each message
and compares it to the current (possibly manual) `ml_label` field stored in the DB.
"""

import csv
from pathlib import Path
import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()
from tracker.models import Message
from ml_subject_classifier import predict_subject_type

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "review_reports"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "reviewed_disagreements.csv"

fieldnames = [
    "message_id",
    "thread_id",
    "timestamp",
    "reviewed",
    "subject",
    "stored_label",
    "stored_conf",
    "ml_label",
    "ml_conf",
    "ml_method",
]

with OUT.open("w", encoding="utf-8", newline="") as outf:
    writer = csv.DictWriter(outf, fieldnames=fieldnames)
    writer.writeheader()

    qs = Message.objects.filter(reviewed=True).order_by("-timestamp")
    for msg in qs:
        # Build text for ML prediction (subject + body); the predictor expects sender optional
        body = (msg.body or "")[:20000] if hasattr(msg, "body") else ""
        ml = predict_subject_type(
            msg.subject or "",
            body,
            sender=(msg.sender or "") if hasattr(msg, "sender") else "",
        )
        ml_label = ml.get("label") if ml else ""
        ml_conf = ml.get("confidence") or ml.get("proba") or 0.0

        stored_label = (msg.ml_label or "").strip()
        stored_conf = getattr(msg, "confidence", None) or 0.0

        if (stored_label or "").strip().lower() != (ml_label or "").strip().lower():
            writer.writerow(
                {
                    "message_id": msg.id,
                    "thread_id": msg.thread_id,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else "",
                    "reviewed": True,
                    "subject": (msg.subject or "").replace("\n", " "),
                    "stored_label": stored_label,
                    "stored_conf": stored_conf,
                    "ml_label": (ml_label or "").strip(),
                    "ml_conf": ml_conf,
                    "ml_method": ml.get("method") if ml else "ml",
                }
            )

print(
    f"Wrote disagreements to: {OUT} (rows where stored label != ML prediction for reviewed messages)"
)
