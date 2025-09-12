# parser.py
import os
import re
import json
import base64
import html
import joblib
from pathlib import Path
from email.utils import parsedate_to_datetime, parseaddr
from bs4 import BeautifulSoup
from db import insert_email_text, insert_or_update_application, is_valid_company
from datetime import datetime, timedelta
from db_helpers import get_application_by_sender, build_company_job_index

# --- Load patterns.json ---
PATTERNS_PATH = Path(__file__).parent / "patterns.json"
if PATTERNS_PATH.exists():
    with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
        patterns_data = json.load(f)
    PATTERNS = patterns_data
    KNOWN_COMPANIES = {c.lower() for c in patterns_data.get("aliases", {}).values()}
    DOMAIN_TO_COMPANY = {k.lower(): v for k, v in patterns_data.get("domain_to_company", {}).items()}
else:
    PATTERNS = {}
    KNOWN_COMPANIES = set()
    DOMAIN_TO_COMPANY = {}

# --- ATS domains for display-name extraction ---
ATS_DOMAINS = {
    "myworkday.com",
    "jobvite.com",
    "greenhouse-mail.io",
    "smartrecruiters.com",
    "pageuppeople.com",
    "icims.com"
}

PARSER_VERSION = "1.0.0"

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

def is_correlated_message(sender_email, sender_domain, msg_date):
    """
    True if sender matches an existing application and msg_date is within 1 year after first_sent.
    """
    app = get_application_by_sender(sender_email, sender_domain)
    if not app:
        return False

    try:
        app_date = datetime.strptime(app['first_sent'], "%Y-%m-%d %H:%M:%S")
        msg_dt = datetime.strptime(msg_date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False

    one_year_later = app_date + timedelta(days=365)
    return app_date <= msg_dt <= one_year_later

def predict_company(subject, body):
    """Predict company name using the trained ML model."""
    if not ml_enabled:
        return None
    text = (subject or "") + " " + (body or "")
    X = vectorizer.transform([text])
    pred_encoded = clf.predict(X)[0]
    return label_encoder.inverse_transform([pred_encoded])[0]

def should_ignore(subject, body):
    """Return True if subject/body matches ignore patterns."""
    subj_lower = subject.lower()
    ignore_patterns = PATTERNS.get("ignore", [])
    return any(p.lower() in subj_lower  for p in ignore_patterns)

def extract_metadata(service, msg_id):
    """Extract subject, date, thread_id, labels, sender, sender_domain, and body text from a Gmail message."""
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    headers = msg['payload']['headers']

    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
    date_raw = next((h['value'] for h in headers if h['name'] == 'Date'), '')
    try:
        date_obj = parsedate_to_datetime(date_raw)
        date_str = date_obj.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        date_str = date_raw

    sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
    _, email_addr = parseaddr(sender)
    match = re.search(r'@([A-Za-z0-9.-]+)$', email_addr)
    sender_domain = match.group(1).lower() if match else ''

    thread_id = msg['threadId']
    label_ids = msg.get('labelIds', [])
    labels = ','.join(label_ids)  # raw IDs unless you re-add get_label_map()

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
            break
        elif mime_type == 'text/html' and not body:
            soup = BeautifulSoup(decoded, 'html.parser')
            body = html.unescape(soup.get_text(separator=' ', strip=True))

    return {
        'thread_id': thread_id,
        'subject': subject,
        'body': body,
        'date': date_str,
        'labels': labels,
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sender': sender,
        'sender_domain': sender_domain,
        'parser_version': PARSER_VERSION
    }

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

def classify_message(body):
    """Classify message body into a status category based on patterns.json."""
    body_lower = body.lower()
    if any(p in body_lower for p in PATTERNS.get('rejection', [])):
        return 'rejection'
    if any(p in body_lower for p in PATTERNS.get('interview', [])):
        return 'interview'
    if any(p in body_lower for p in PATTERNS.get('follow_up', [])):
        return 'follow_up'
    if any(p in body_lower for p in PATTERNS.get('application', [])):
        return 'application'
    if any(p in body_lower for p in PATTERNS.get('response', [])):
        return 'response'
    return ''

def parse_subject(subject, sender=None, sender_domain=None):
    """Extract company, job title, and job ID from subject line, sender, and optionally sender domain."""
    company = ''
    job_title = ''
    job_id = ''
    subject_clean = subject.strip()
    subj_lower = subject_clean.lower()
    domain_lower = sender_domain.lower() if sender_domain else None

    # Colon-prefix
    m = re.match(r"^([A-Z][A-Za-z0-9&.\- ]+):", subject_clean)
    if m:
        company = m.group(1).strip()

    # Known companies
    if not company and KNOWN_COMPANIES:
        for known in KNOWN_COMPANIES:
            if known in subj_lower:
                company = known.title()
                break

    # Domain mapping
    if not company and domain_lower and domain_lower in DOMAIN_TO_COMPANY:
        company = DOMAIN_TO_COMPANY[domain_lower]

    # ATS domain → display name
    if not company and domain_lower in ATS_DOMAINS and sender:
        display_name, _ = parseaddr(sender)
        cleaned = re.sub(
            r'\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring)\b',
            '',
            display_name,
            flags=re.I
        ).strip()
        if cleaned:
            company = cleaned

    # Regex patterns
    patterns = [
        (r'application (?:to|for|with)\s+([A-Z][\w\s&\-]+)', re.IGNORECASE),
        (r'(?:from|with|at)\s+([A-Z][\w\s&\-]+)', re.IGNORECASE),
        (r'^([A-Z][\w\s&\-]+)\s+(Job|Application|Interview)', 0),
        (r'-\s*([A-Z][\w\s&\-]+)\s*-\s*', 0),
        (r'^([A-Z][\w\s&\-]+)\s+application', 0)
    ]
    for pat, flags in patterns:
        if not company:
            match = re.search(pat, subject_clean, flags)
            if match:
                company = match.group(1).strip()

    # Job title
    title_match = re.search(
        r'job\s+(?:submission\s+for|application\s+for|title\s+is)?\s*([\w\s\-]+)',
        subject_clean,
        re.IGNORECASE
    )
    job_title = title_match.group(1).strip() if title_match else ''

    # Job ID
    id_match = re.search(
        r'(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)',
        subject_clean,
        re.IGNORECASE
    )
    job_id = id_match.group(1).strip() if id_match else ''
    
    return {
        'company': company,
        'job_title': job_title,
        'job_id': job_id
    }

def ingest_message(service, msg_id):
    try:
        metadata = extract_metadata(service, msg_id)
    except Exception as e:
        print(f"❌ Failed to extract data for {msg_id}: {e}")
        return

    # ✅ Always classify and extract dates first
    status = classify_message(metadata['body'])
    status_dates = extract_status_dates(metadata['body'], metadata['date'])

        # ✅ Only ignore if status is empty, not correlated, and matches ignore patterns
    if not status:
        if is_correlated_message(metadata['sender'], metadata['sender_domain'], metadata['date']):
            pass  # keep it
        elif should_ignore(metadata['subject'], metadata['body']):
            print(f"⚠️ Ignored: {metadata['subject']}")
            return

    # Store subject/body for ML training
    insert_email_text(msg_id, metadata['subject'], metadata['body'])

    # Parse subject for initial extraction
    parsed_subject = parse_subject(
        metadata['subject'],
        sender=metadata.get('sender'),
        sender_domain=metadata.get('sender_domain')
    )

    company = parsed_subject['company'] or ""
    company_norm = company.lower()

    # --- Tier 1 & 2: Whitelist or heuristic keep ---
    if company_norm not in KNOWN_COMPANIES and not is_valid_company('company'):
        company = ""

    # --- Tier 3: Fallback enrichment from sender_domain mapping ---
    if not company:
        mapped = DOMAIN_TO_COMPANY.get(metadata.get('sender_domain', '').lower(), "")
        if mapped:
            company = mapped

    # --- Tier 4: ML fallback ---
    if not company or company.lower() in ('careers', 'hiring team', 'recruiting'):
        predicted = predict_company(metadata['subject'], metadata['body'])
        parsed_subject['predicted_company'] = predicted or ''
        if predicted and not company:
            company = predicted
    else:
        parsed_subject['predicted_company'] = ''

    # Final record assembly
    record = {
        'thread_id': metadata['thread_id'],
        'company': company,
        'predicted_company': parsed_subject.get('predicted_company', ''),
        'job_title': parsed_subject['job_title'],
        'job_id': parsed_subject['job_id'],
        'first_sent': metadata['date'],
        'response_date': status_dates['response_date'],
        'follow_up_dates': status_dates['follow_up_dates'],
        'rejection_date': status_dates['rejection_date'],
        'interview_date': status_dates['interview_date'],
        'status': status,
        'labels': metadata['labels'],
        'subject': metadata['subject'],
        'sender': metadata['sender'],
        'sender_domain': metadata['sender_domain'],
        'last_updated': metadata['last_updated']
    }

    # Build composite index once, from cleaned company/job_title/job_id
    record['company_job_index'] = build_company_job_index(
        record.get('company', ''),
        record.get('job_title', ''),
        record.get('job_id', '')
    )

    print(f"🔍 company_job_index: {record['company_job_index']}")

    insert_or_update_application(record)
    print(f"✅ Logged: {metadata['subject']}")