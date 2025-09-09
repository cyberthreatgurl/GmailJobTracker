import base64
import re
import os
import json
from datetime import datetime
from db import insert_email_text, insert_or_update_application, init_db
from bs4 import BeautifulSoup
import html
import joblib  # For loading ML model artifacts

# --- Versioning ---
PARSER_VERSION = '2.2.0'  # Incremented for ML integration
SCHEMA_VERSION = '1.2.0'  # Incremented for predicted_company column

# Load known companies from a file (one per line, case-insensitive)
KNOWN_COMPANIES = set()
if os.path.exists("known_companies.txt"):
    with open("known_companies.txt", "r", encoding="utf-8") as f:
        KNOWN_COMPANIES = {line.strip().lower() for line in f if line.strip()}
        
# --- Load patterns.json for ignore rules, status phrases, etc. ---
with open('patterns.json', encoding='utf-8') as f:
    PATTERNS = json.load(f)

# --- Load ML model artifacts at startup ---
try:
    clf = joblib.load("model/company_classifier.pkl")
    vectorizer = joblib.load("model/vectorizer.pkl")
    label_encoder = joblib.load("model/label_encoder.pkl")
    ml_enabled = True
    print("🤖 ML model loaded for company prediction.")
except FileNotFoundError:
    ml_enabled = False
    print("⚠️ ML model not found — skipping prediction.")

def predict_company(subject, body):
    """Predict company name using the trained ML model."""
    if not ml_enabled:
        return None
    text = (subject or "") + " " + (body or "")
    X = vectorizer.transform([text])
    pred_encoded = clf.predict(X)[0]
    return label_encoder.inverse_transform([pred_encoded])[0]

def get_label_map(service):
    """Fetch Gmail label ID → name mapping."""
    labels = service.users().labels().list(userId='me').execute()
    return {label['id']: label['name'] for label in labels['labels']}

def extract_metadata(service, msg_id):
    """Extract subject, date, thread_id, labels, and body text from a Gmail message."""
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    headers = msg['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
    date_raw = next((h['value'] for h in headers if h['name'] == 'Date'), '')
    thread_id = msg['threadId']
    label_ids = msg.get('labelIds', [])

    # Map label IDs to human-readable names
    label_map = get_label_map(service)
    label_names = [label_map.get(lid, lid) for lid in label_ids]

    # Parse date safely
    try:
        date_obj = datetime.strptime(date_raw[:25], '%a, %d %b %Y %H:%M:%S')
        date = date_obj.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        date = date_raw

    # Decode body
    body = ''
    parts = msg['payload'].get('parts', [])
    for part in parts:
        mime_type = part.get('mimeType')
        data = part['body'].get('data')
        if not data:
            continue

        decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        if mime_type == 'text/plain':
            body = decoded.strip()
            break  # Prefer plain text
        elif mime_type == 'text/html' and not body:
            soup = BeautifulSoup(decoded, 'html.parser')
            body = soup.get_text(separator=' ', strip=True)
            body = html.unescape(body)

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
    """Classify message type based on patterns.json categories."""
    body_lower = body.lower()
    for category, phrases in PATTERNS.items():
        for phrase in phrases:
            if phrase in body_lower:
                return category
    return 'outreach'

def extract_status_dates(body, received_date):
    """Extract key status dates from email body."""
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
    """Lowercase, strip punctuation, collapse whitespace."""
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower().strip()

def should_ignore(subject, body):
    """Check if subject/body matches any ignore patterns."""
    subject_lower = subject.lower()
    body_lower = body.lower()
    for phrase in PATTERNS.get("ignore", []):
        if phrase in subject_lower or phrase in body_lower:
            print(f"Ignored due to pattern: '{phrase}' in subject/body")
            return True
    return False

# Load known companies from file (one per line)
KNOWN_COMPANIES = set()
if os.path.exists("known_companies.txt"):
    with open("known_companies.txt", "r", encoding="utf-8") as f:
        KNOWN_COMPANIES = {line.strip().lower() for line in f if line.strip()}

# Load domain-to-company mapping from JSON
DOMAIN_TO_COMPANY = {}
if os.path.exists("domain_to_company.json"):
    with open("domain_to_company.json", "r", encoding="utf-8") as f:
        DOMAIN_TO_COMPANY = json.load(f)

def parse_subject(subject, sender_domain=None):
    """Extract company, job title, and job ID from subject line and optionally sender domain."""
    company = ''
    job_title = ''
    job_id = ''
    subject_clean = subject.strip()

    # 1. Colon-prefix rule: "MITRE: Thank you..."
    m = re.match(r"^([A-Z][A-Za-z0-9&.\- ]+):", subject_clean)
    if m:
        company = m.group(1).strip()

    # 2. Known companies list match
    if not company and KNOWN_COMPANIES:
        subj_lower = subject_clean.lower()
        for known in KNOWN_COMPANIES:
            if known in subj_lower:
                company = known.title()
                break

    # 3. Sender domain mapping
    if not company and sender_domain:
        domain_lower = sender_domain.lower()
        if domain_lower in DOMAIN_TO_COMPANY:
            company = DOMAIN_TO_COMPANY[domain_lower]

    # --- Existing Pattern 1: "Your application to Armis Security"
    if not company:
        match = re.search(r'application (?:to|for|with)\s+([A-Z][\w\s&\-]+)', subject_clean, re.IGNORECASE)
        if match:
            company = match.group(1).strip()

    # --- Existing Pattern 2: "Interview Confirmation from Partner Forces"
    if not company:
        match = re.search(r'(?:from|with|at)\s+([A-Z][\w\s&\-]+)', subject_clean, re.IGNORECASE)
        if match:
            company = match.group(1).strip()

    # --- Existing Pattern 3: "CrowdStrike Job Application Confirmation"
    if not company:
        match = re.search(r'^([A-Z][\w\s&\-]+)\s+(Job|Application|Interview)', subject_clean)
        if match:
            company = match.group(1).strip()

    # --- Existing Pattern 4: "Position You Applied For - Leidos - Cybersecurity PM"
    if not company:
        match = re.search(r'-\s*([A-Z][\w\s&\-]+)\s*-\s*', subject_clean)
        if match:
            company = match.group(1).strip()

    # --- Existing Pattern 5: "Virginia Tech application status"
    if not company:
        match = re.search(r'^([A-Z][\w\s&\-]+)\s+application', subject_clean)
        if match:
            company = match.group(1).strip()

    # Job title extraction
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
    
def ingest_message(service, msg_id, conn=None):
    try:
        metadata = extract_metadata(service, msg_id)
    except Exception as e:
        print(f"Failed to extract data for {msg_id}: {e}")
        return

    # ✅ Apply ignore patterns from patterns.json
    if should_ignore(metadata['subject'], metadata['body']):
        print(f"Ignored: {metadata['subject']}")
        return

    # Store subject and body for ML training
    insert_email_text(msg_id, metadata['subject'], metadata['body'])

    # Classify and extract dates
    status = classify_message(metadata['body'])
    status_dates = extract_status_dates(metadata['body'], metadata['date'])

    # Parse subject for company/job info
    parsed_subject = parse_subject(metadata['subject'])
    company = parsed_subject['company']
    job_title = parsed_subject['job_title']
    job_id = parsed_subject['job_id']

    # ML fallback if no company OR placeholder "Intel"
    predicted_company = ''
    if not company or company.lower() == "intel":
        predicted = predict_company(metadata['subject'], metadata['body'])
        print(f"Predicted company: {predicted} for message ID {msg_id}")
        if predicted:
            predicted_company = predicted
            company = predicted
            print(f"🔮 [ML USED] Predicted company '{predicted_company}' for message {msg_id}")

    # Build full record for DB
    record = {
        'thread_id': metadata['thread_id'],
        'company': company,
        'predicted_company': predicted_company,
        'job_title': job_title,
        'job_id': job_id,
        'first_sent': metadata['date'],
        'response_date': status_dates['response_date'],
        'follow_up_dates': status_dates['follow_up_dates'],
        'rejection_date': status_dates['rejection_date'],
        'interview_date': status_dates['interview_date'],
        'status': status,
        'labels': metadata['labels'],
        'subject': metadata['subject'],
        'last_updated': metadata['last_updated']
    }

    insert_or_update_application(record)
    print(f"Logged: {metadata['subject']} → {status}")
    