import base64
import re
import json
from email import message_from_bytes
from datetime import datetime

PARSER_VERSION = '2.0.0'  # Reflects regex improvements, ignore logic, and subject parsing overhaul
SCHEMA_VERSION = '1.1.0'

with open('patterns.json') as f:
    PATTERNS = json.load(f)

def get_label_map(service):
    labels = service.users().labels().list(userId='me').execute()
    return {label['id']: label['name'] for label in labels['labels']}

def extract_metadata(service, msg_id):
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    headers = msg['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
    date_raw = next((h['value'] for h in headers if h['name'] == 'Date'), '')
    thread_id = msg['threadId']
    label_ids = msg.get('labelIds', [])

    # Map label IDs to human-readable names
    label_map = get_label_map(service)
    label_names = [label_map.get(lid, lid) for lid in label_ids]

    # Parse date
    try:
        date_obj = datetime.strptime(date_raw[:25], '%a, %d %b %Y %H:%M:%S')
        date = date_obj.strftime('%Y-%m-%d %H:%M:%S')
    except:
        date = date_raw

    # Decode body
    body = ''
    parts = msg['payload'].get('parts', [])
    for part in parts:
        if part['mimeType'] == 'text/plain':
            data = part['body'].get('data')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                break
    return {
        'subject': subject,
        'date': date,
        'thread_id': thread_id,
        'body': body,
        'labels': ','.join(label_names),
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'parser_version': PARSER_VERSION
    }

def classify_message(body):
    body_lower = body.lower()
    for category, phrases in PATTERNS.items():
        for phrase in phrases:
            if phrase in body_lower:
                return category
    return 'outreach'

def parse_subject(subject):
    company = ''
    job_title = ''
    job_id = ''

    subject_clean = subject.strip()

    # Pattern 1: "Your application to Armis Security"
    match = re.search(r'application (?:to|for|with)\s+([A-Z][\w\s&\-]+)', subject_clean, re.IGNORECASE)
    if match:
        company = match.group(1).strip()

    # Pattern 2: "Interview Confirmation from Partner Forces"
    if not company:
        match = re.search(r'(?:from|with|at)\s+([A-Z][\w\s&\-]+)', subject_clean, re.IGNORECASE)
        if match:
            company = match.group(1).strip()

    # Pattern 3: "CrowdStrike Job Application Confirmation"
    if not company:
        match = re.search(r'^([A-Z][\w\s&\-]+)\s+(Job|Application|Interview)', subject_clean)
        if match:
            company = match.group(1).strip()

    # Pattern 4: "Position You Applied For - Leidos - Cybersecurity PM"
    if not company:
        match = re.search(r'-\s*([A-Z][\w\s&\-]+)\s*-\s*', subject_clean)
        if match:
            company = match.group(1).strip()

    # Pattern 5: "Virginia Tech application status"
    if not company:
        match = re.search(r'^([A-Z][\w\s&\-]+)\s+application', subject_clean)
        if match:
            company = match.group(1).strip()

    # Job title extraction (fallback)
    title_match = re.search(r'job\s+(?:submission\s+for|application\s+for|title\s+is)?\s*([\w\s\-]+)', subject_clean, re.IGNORECASE)
    if title_match:
        job_title = title_match.group(1).strip()

    # Job ID extraction
    id_match = re.search(r'(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)', subject_clean, re.IGNORECASE)
    if id_match:
        job_id = id_match.group(1).strip()

    return {
        'company': company,
        'job_title': job_title,
        'job_id': job_id
    }
    
def extract_status_dates(body, received_date):
    body_lower = body.lower()
    dates = {
        'response_date': '',
        'rejection_date': '',
        'interview_date': '',
        'follow_up_dates': ''
    }

    if any(p in body_lower for p in PATTERNS.get('response', [])):
        dates['response_date'] = received_date
    if any(p in body_lower for p in PATTERNS.get('rejection', [])):
        dates['rejection_date'] = received_date
    if any(p in body_lower for p in PATTERNS.get('interview', [])):
        dates['interview_date'] = received_date
    if any(p in body_lower for p in PATTERNS.get('follow_up', [])):
        dates['follow_up_dates'] = received_date


    return dates

def normalize_text(text):
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation and emojis
    text = re.sub(r'\s+', ' ', text)     # Collapse whitespace
    return text.lower().strip()

def should_ignore(subject, body):
    combined = normalize_text(f"{subject} {body}")
    ignore_phrases = [normalize_text(p) for p in PATTERNS.get('ignore', [])]
    return any(phrase in combined for phrase in ignore_phrases)