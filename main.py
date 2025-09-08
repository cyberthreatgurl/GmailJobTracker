from gmail_auth import get_gmail_service
from parser import (
    extract_metadata,
    classify_message,
    parse_subject,
    extract_status_dates,
    should_ignore,
    PATTERNS
)
from db import init_db, insert_or_update_application

# Initialize Gmail and DB
service = get_gmail_service()
init_db()
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
            metadata = extract_metadata(service, msg_id)
        except Exception as e:
            print(f"Failed to extract metadata for {msg_id}: {e}")
            continue

        if should_ignore(metadata['subject'], metadata['body']):
            print(f"Ignored: {metadata['subject']}")
            continue

        status = classify_message(metadata['body'])
        parsed_subject = parse_subject(metadata['subject'])
        status_dates = extract_status_dates(metadata['body'], metadata['date'])

        record = {
            'thread_id': metadata['thread_id'],
            'company': parsed_subject['company'],
            'job_title': parsed_subject['job_title'],
            'job_id': parsed_subject['job_id'],
            'first_sent': metadata['date'],
            'response_date': status_dates['response_date'],
            'follow_up_dates': status_dates['follow_up_dates'],
            'rejection_date': status_dates['rejection_date'],
            'interview_date': status_dates['interview_date'],
            'status': status,
            'labels': metadata['labels'],
            'notes': metadata['subject'],
            'last_updated': metadata['last_updated']
        }

        insert_or_update_application(record)
        print(f"Logged: {metadata['subject']} → {status}")

sync_messages()