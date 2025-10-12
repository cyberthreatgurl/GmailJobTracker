# main.py

import os
import sys
from datetime import datetime
import django
from django.utils.timezone import localdate
from django.contrib.auth import get_user_model

import argparse

# --- Initialize Gmail and DB ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import IngestionStats
from gmail_auth import get_gmail_service
from parser import ingest_message, PATTERNS
from db import init_db

# --- Parse CLI flags ---
parser = argparse.ArgumentParser()
parser.add_argument("--limit-msg", help="Only ingest this single msg_id")
args = parser.parse_args()

# --- Initialize Gmail ---
service = get_gmail_service()

# --- Optional single-message ingest ---
if args.limit_msg:
    try:
        result = ingest_message(service, args.limit_msg)
        print(f"[single] {result or '❓ Unknown result'} for {args.limit_msg}")
    except Exception as e:
        print(f"[single] ❌ Failed to ingest {args.limit_msg}: {e}")
    sys.exit(0)

# --- Full sync ---
try:
    init_db()
except Exception as e:
    print(f"❌ Failed to initialize database: {e}")
    sys.exit(1)

def prompt_superuser():
    User = get_user_model()
    if not User.objects.filter(is_superuser=True).exists():
        print("🔐 No superuser found. Create one now:")
        os.system("python manage.py createsuperuser")

print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Database initialized.")

profile = service.users().getProfile(userId="me").execute()
print(f"Connected to Gmail account: {profile['emailAddress']}")


def build_query():
    """Build Gmail search query from static subject terms and patterns.json body terms."""
    subject_terms = ["job", "application", "resume", "interview", "position"]
    subject_query = " OR ".join(subject_terms)

    body_terms = (
        (
            PATTERNS.get("application", [])
            + PATTERNS.get("interview", [])
            + PATTERNS.get("follow_up", [])
            + PATTERNS.get("rejection", [])
        )
        if PATTERNS
        else []
    )

    body_query = " OR ".join(f'"{term}"' for term in body_terms) if body_terms else ""

    if body_query:
        return f"(subject:({subject_query}) OR body:({body_query})) newer_than:365d"
    else:
        return f"(subject:({subject_query})) newer_than:365d"


def fetch_all_messages(service, query):
    """Fetch all Gmail messages matching the query."""
    messages = []
    next_page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=100, pageToken=next_page_token)
            .execute()
        )

        messages.extend(response.get("messages", []))
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return messages


def sync_messages():
       
    """Run a full sync of Gmail messages into the database."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting sync...")
    query = build_query()
    print(f"Using Gmail query: {query}")

    messages = fetch_all_messages(service, query)
    print(f"Found {len(messages)} messages matching query.")
   
    
    new_messages = []
    for idx, msg in enumerate(messages, start=1):
        msg_id = msg["id"]
        try:
            result = ingest_message(service, msg_id)
            if result == "ignored":
                print(f"[{idx}/{len(messages)}] ⚠️ Ignored {msg_id}")
            elif result == "inserted":
                new_messages.append(msg_id)
                print(f"[{idx}/{len(messages)}] ✅ Inserted {msg_id}")
            elif result == "skipped":
                print(f"[{idx}/{len(messages)}] ⏩ Skipped duplicate {msg_id}")
            else:
                print(f"[{idx}/{len(messages)}] ❓ Unknown result for {msg_id}")
        except Exception as e:
            print(f"[{idx}/{len(messages)}] ❌ Failed to ingest {msg_id}: {e}")
            continue
        
    if not new_messages:
        print("No new messages to process. Exiting.")
        return
    
    today = localdate()
    stats, _ = IngestionStats.objects.get_or_create(date=today)
    print(
        f"Summary: {stats.total_inserted} inserted, "
        f"{stats.total_ignored} ignored, "
        f"{stats.total_skipped} skipped"
    )

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Sync complete.")


if __name__ == "__main__":
    init_db()
    sync_messages()
    prompt_superuser()
    