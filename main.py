# main.py

import os
import sys
from datetime import datetime
import django

# --- Initialize Gmail and DB --- 
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")   
django.setup()

from gmail_auth import get_gmail_service
from parser import ingest_message, PATTERNS
from db import init_db

service = get_gmail_service()

try:
    init_db()
except Exception as e:
    print(f"❌ Failed to initialize database: {e}")
    sys.exit(1)

print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Database initialized.")

profile = service.users().getProfile(userId='me').execute()
print(f"Connected to Gmail account: {profile['emailAddress']}")

def build_query():
    """Build Gmail search query from static subject terms and patterns.json body terms."""
    # Subject keywords (static)
    subject_terms = ['job', 'application', 'resume', 'interview', 'position']
    subject_query = ' OR '.join(subject_terms)

    # Body keywords from patterns.json (guard against missing keys)
    body_terms = (
        PATTERNS.get('application', []) +
        PATTERNS.get('interview', []) +
        PATTERNS.get('follow_up', []) +
        PATTERNS.get('rejection', [])
    ) if PATTERNS else []

    body_query = ' OR '.join(f'"{term}"' for term in body_terms) if body_terms else ''

    # Combine subject/body queries
    if body_query:
        return f'(subject:({subject_query}) OR body:({body_query})) newer_than:365d'
    else:
        return f'(subject:({subject_query})) newer_than:365d'

def fetch_all_messages(service, query):
    """Fetch all Gmail messages matching the query."""
    messages = []
    next_page_token = None

    while True:
        response = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=100,
            pageToken=next_page_token
        ).execute()

        messages.extend(response.get('messages', []))
        next_page_token = response.get('nextPageToken')
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

    for idx, msg in enumerate(messages, start=1):
        msg_id = msg['id']
        try:
            result = ingest_message(service, msg_id)
            if result == "ignored":
                print(f"[{idx}/{len(messages)}] ⚠️ Ignored {msg_id}")
            elif result == "inserted":
                print(f"[{idx}/{len(messages)}] ✅ Inserted {msg_id}")
            elif result == "skipped":
                print(f"[{idx}/{len(messages)}] ⏩ Skipped duplicate {msg_id}")
            else:
                print(f"[{idx}/{len(messages)}] ❓ Unknown result for {msg_id}")
        except Exception as e:
            print(f"[{idx}/{len(messages)}] ❌ Failed to ingest {msg_id}: {e}")
            continue
        else:
            print(f"[{idx}/{len(messages)}] ✅ Ingested {msg_id}")

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Sync complete.")

if __name__ == "__main__":
    sync_messages()