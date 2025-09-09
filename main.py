from gmail_auth import get_gmail_service
from parser import (
    ingest_message,
    PATTERNS,
)
from db import init_db
import sys

# Initialize Gmail and DB
service = get_gmail_service()

try:
    init_db()
except Exception as e:
    print(f"❌ Failed to initialize database: {e}")
    sys.exit(1)

print("Database initialized.")

profile = service.users().getProfile(userId='me').execute()
print(f"Connected to Gmail account: {profile['emailAddress']}")

def build_query():
    # Subject keywords (static)
    subject_terms = ['job', 'application', 'resume', 'interview', 'position']
    subject_query = ' OR '.join(subject_terms)

    # Body keywords from patterns.json
    body_terms = (
        PATTERNS.get('application', []) +
        PATTERNS.get('interview', []) +
        PATTERNS.get('follow_up', []) +
        PATTERNS.get('rejection', [])
    )
    body_query = ' OR '.join(f'"{term}"' for term in body_terms)

    return f'(subject:({subject_query}) OR body:({body_query})) newer_than:180d'

def fetch_all_messages(service, query):
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
    query = build_query()
    print(f"Using Gmail query: {query}")
    messages = fetch_all_messages(service, query)

    for msg in messages:
        msg_id = msg['id']
        try:
            ingest_message(service, msg_id)
        except Exception as e:
            print(f"Failed to ingest {msg_id}: {e}")
            continue

if __name__ == "__main__":
    sync_messages()