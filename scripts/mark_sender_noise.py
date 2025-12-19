import os
import sys
import json
from pathlib import Path

sys.path.insert(0, r"C:\Users\kaver\code\GmailJobTracker")
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking
from django.db.models import Q


def main(sender_email: str, apply_changes: bool = True):
    ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    scripts_dir = Path("scripts")
    scripts_dir.mkdir(exist_ok=True)

    qs = Message.objects.filter(sender__icontains=sender_email).exclude(
        ml_label="noise"
    )
    total = qs.count()
    print(f"Found {total} message(s) from {sender_email} not labeled noise")
    if total == 0:
        return

    rows = []
    thread_ids = set()
    for m in qs.order_by("-timestamp"):
        rows.append(
            {
                "id": m.id,
                "msg_id": m.msg_id,
                "thread_id": m.thread_id,
                "sender": m.sender,
                "subject": (m.subject or "")[:200],
                "ml_label": m.ml_label,
                "confidence": float(m.confidence or 0),
                "company_id": m.company.id if m.company_id else None,
                "company_name": getattr(m.company, "name", None),
            }
        )
        if m.thread_id:
            thread_ids.add(m.thread_id)

    backup_path = (
        scripts_dir
        / f'mark_sender_noise_backup_{sender_email.replace("@","_at_")}_{ts}.json'
    )
    with backup_path.open("w", encoding="utf-8") as fh:
        json.dump({"ts": ts, "sender": sender_email, "messages": rows}, fh, indent=2)
    print(f"Wrote backup for messages to: {backup_path}")

    if not apply_changes:
        print("Dry-run: no changes applied")
        return

    updated_msg = 0
    updated_tt = 0
    for m in qs:
        try:
            m.ml_label = "noise"
            m.confidence = 0.99
            # Clear company assignment for personal messages
            m.company = None
            m.company_source = ""
            m.save()
            updated_msg += 1
        except Exception as e:
            print(f"Failed to update Message id={m.id}: {e}")

    # Update related ThreadTracking rows: set ml_label to noise where all messages in thread are noise or this sender caused noise
    for tid in thread_ids:
        try:
            tt = ThreadTracking.objects.filter(thread_id=tid).first()
            if not tt:
                continue
            # If any message in the thread is not noise, skip changing thread-level label
            non_noise_exists = (
                Message.objects.filter(thread_id=tid).exclude(ml_label="noise").exists()
            )
            if not non_noise_exists:
                tt.ml_label = "noise"
                tt.ml_confidence = 0.99
                tt.save()
                updated_tt += 1
        except Exception as e:
            print(f"Failed to update ThreadTracking for thread_id={tid}: {e}")

    print(
        f"Updated {updated_msg} Message(s) and {updated_tt} ThreadTracking(s) for sender {sender_email}"
    )


if __name__ == "__main__":
    # default to apply; pass --dry-run to skip changes
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("sender")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.sender, apply_changes=not args.dry_run)
