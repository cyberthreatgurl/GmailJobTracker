"""Utility: mark a Message.reviewed=False by msg_id and print status.

Usage:
  .\.venv\Scripts\python.exe scripts\unmark_reviewed.py <msg_id>

This runs inside the project's Django settings and toggles the reviewed flag
for targeted re-ingestion when you know the message should be re-parsed.
"""
import sys
import os

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: unmark_reviewed.py <msg_id>")
        sys.exit(2)

    msg_id = sys.argv[1]

    # Ensure Django settings are configured the same as parser.py
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
    import django

    django.setup()
    from tracker.models import Message

    try:
        m = Message.objects.filter(msg_id=msg_id).first()
        if not m:
            print(f"Message not found: {msg_id}")
            sys.exit(1)
        print(f"Before: msg_id={m.msg_id}, reviewed={m.reviewed}, ml_label={m.ml_label}, confidence={m.confidence}")
        m.reviewed = False
        m.save()
        print(f"After: msg_id={m.msg_id}, reviewed={m.reviewed}")
    except Exception as e:
        print(f"Error updating message: {e}")
        raise
