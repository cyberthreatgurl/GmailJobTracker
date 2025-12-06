"""Unmark a Message reviewed and re-ingest it from Gmail (by msg_id).

Usage:
  .\.venv\Scripts\python.exe scripts\reingest_msg.py <msg_id>

This will:
 - set Message.reviewed=False for the given Message.msg_id
 - call Gmail API via `get_gmail_service()` and pass the Gmail msg id to parser.ingest_message
 - print the ingest result

Note: Requires valid `model/token.pickle` and `json/credentials.json` for Gmail OAuth.
"""
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: reingest_msg.py <msg_id>")
        sys.exit(2)

    target_msg_id = sys.argv[1]

    # Ensure repo root is on sys.path so Django project modules import correctly
    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
    import django

    django.setup()
    from tracker.models import Message
    from gmail_auth import get_gmail_service
    from parser import ingest_message

    m = Message.objects.filter(msg_id=target_msg_id).first()
    if not m:
        print(f"Message not found with msg_id={target_msg_id}")
        sys.exit(1)

    print(f"Before: msg_id={m.msg_id}, reviewed={m.reviewed}, ml_label={m.ml_label}, confidence={m.confidence}")
    m.reviewed = False
    m.save()
    print("Cleared reviewed flag; attempting re-ingest from Gmail...")

    service = get_gmail_service()
    if not service:
        print("Failed to initialize Gmail service. Check OAuth credentials/token.")
        sys.exit(2)

    try:
        res = ingest_message(service, target_msg_id)
        print(f"Re-ingest result: {res}")
        # Show refreshed DB state
        m.refresh_from_db()
        print(f"After: msg_id={m.msg_id}, reviewed={m.reviewed}, ml_label={m.ml_label}, confidence={m.confidence}")
    except Exception as e:
        print(f"Re-ingest failed: {e}")
        raise
