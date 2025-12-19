"""Small re-classify helper for uploaded eml files.

This module is import-safe and exposes `reclassify_eml_text(raw_text)` for
scripts/tests to call without executing on import.
"""

import sys
import os
from email.utils import parseaddr
from pathlib import Path

sys.path.insert(0, r"C:\Users\kaver\code\GmailJobTracker")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from parser import parse_raw_message, predict_with_fallback
from ml_subject_classifier import predict_subject_type
from tracker.models import Message, ThreadTracking
from tracker.label_helpers import label_message_and_propagate


def reclassify_eml_text(raw_text: str) -> dict:
    """Parse raw .eml text, run classification, and update the matching Message/ThreadTracking.

    Returns a dict with results for testing/verification.
    """
    parsed = parse_raw_message(raw_text)
    subject = parsed.get("subject", "")
    body = parsed.get("body", "")
    sender = parsed.get("sender", "")
    from_addr = parseaddr(sender)[1]

    ml = predict_with_fallback(
        predict_subject_type,
        subject or "",
        body or "",
        threshold=0.6,
        sender=from_addr or "",
    )
    ml_label = ml.get("label") if ml else None
    ml_conf = float(ml.get("confidence", 0.0) if ml else 0.0)

    # Extract Message-ID
    import re

    m = re.search(r"^Message-ID:\s*<([^>]+)>", raw_text, re.I | re.M)
    msg_id = m.group(1) if m else None
    msg = None
    if msg_id:
        msg = Message.objects.filter(msg_id=msg_id).first()
    if not msg:
        # fallback to subject-based find
        msg = (
            Message.objects.filter(subject__icontains=subject[:40])
            .order_by("-timestamp")
            .first()
        )

    if not msg:
        return {"found": False, "msg_id": msg_id}

    # Use label helper to save and propagate
    label_message_and_propagate(msg, ml_label, ml_conf)

    # Also ensure ThreadTracking status/fields updated if present
    tt = (
        ThreadTracking.objects.filter(thread_id=msg.thread_id).first()
        if msg.thread_id
        else None
    )
    if tt and ml_label:
        tt.ml_label = ml_label
        tt.ml_confidence = ml_conf
        tt.status = ml_label
        tt.save()

    return {
        "found": True,
        "message_id": msg.id,
        "ml_label": ml_label,
        "ml_confidence": ml_conf,
    }


if __name__ == "__main__":
    # Simple CLI for manual runs
    p = Path(os.getcwd()) / "sample.eml"
    if not p.exists():
        print("Provide a path to an .eml file or place sample.eml in cwd")
        sys.exit(1)
    raw = p.read_text(encoding="utf-8", errors="ignore")
    print(reclassify_eml_text(raw))
