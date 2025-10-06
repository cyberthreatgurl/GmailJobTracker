# parser.py
import os
import re
import json
import base64
import html
import joblib
import django
from django.utils import timezone
from django.utils.timezone import now
from pathlib import Path
from email.utils import parsedate_to_datetime, parseaddr
from bs4 import BeautifulSoup
from db import insert_email_text, insert_or_update_application, is_valid_company
from datetime import datetime, timedelta
from db_helpers import get_application_by_sender, build_company_job_index
from ml_subject_classifier import predict_subject_type
from ml_entity_extraction import extract_entities
from tracker.models import Message, IgnoredMessage, IngestionStats

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()
DEBUG = True
DOMAIN_TO_COMPANY = {
    # example real mappings
    "stripe.com": "Stripe",
    "airbnb.com": "Airbnb",
    "example.com": "MappedCo",  # used in test
}
KNOWN_COMPANIES = [
    "Airbnb",
    "Stripe",
    "Google",
    "Meta",
    "Netflix",
    "Amazon",
    "Microsoft",
]


def get_stats():
    today = now().date()
    stats, _ = IngestionStats.objects.get_or_create(date=today)
    return stats


def log_ignored_message(msg_id, metadata, reason):
    IgnoredMessage.objects.update_or_create(
        msg_id=msg_id,
        defaults={
            "subject": metadata["subject"],
            "body": metadata["body"],
            "sender": metadata["sender"],
            "sender_domain": metadata["sender_domain"],
            "date": metadata["timestamp"],
            "reason": reason,
        },
    )


# --- Load patterns.json ---
PATTERNS_PATH = Path(__file__).parent / "patterns.json"
if PATTERNS_PATH.exists():
    with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
        patterns_data = json.load(f)
    PATTERNS = patterns_data
    KNOWN_COMPANIES = {c.lower() for c in patterns_data.get("aliases", {}).values()}
    DOMAIN_TO_COMPANY = {
        k.lower(): v for k, v in patterns_data.get("domain_to_company", {}).items()
    }
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
    "icims.com",
}

PARSER_VERSION = "1.0.0"

# --- Load ML model artifacts at startup ---
try:
    clf = joblib.load("model/company_classifier.pkl")
    vectorizer = joblib.load("model/vectorizer.pkl")
    label_encoder = joblib.load("model/label_encoder.pkl")
    ml_enabled = True
    if DEBUG:
        print("🤖 ML model loaded for company prediction.")
except FileNotFoundError:
    ml_enabled = False
    if DEBUG:
        print("⚠️ ML model not found — skipping prediction.")


def is_correlated_message(sender_email, sender_domain, msg_date):
    """
    True if sender matches an existing application and msg_date is within 1 year after first_sent.
    """
    app = get_application_by_sender(sender_email, sender_domain)
    if not app:
        return False

    try:
        app_date = datetime.strptime(app["first_sent"], "%Y-%m-%d %H:%M:%S")
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
    return any(p.lower() in subj_lower for p in ignore_patterns)


def extract_metadata(service, msg_id):
    """Extract subject, date, thread_id, labels, sender, sender_domain, and body text from a Gmail message."""
    msg = (
        service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    )
    headers = msg["payload"]["headers"]

    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
    date_raw = next((h["value"] for h in headers if h["name"] == "Date"), "")
    try:
        date_obj = parsedate_to_datetime(date_raw)
        if timezone.is_naive(date_obj):
            date_obj = timezone.make_aware(date_obj)  # assume settings.TIME_ZONE
        date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        date_str = date_raw

    sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
    parsed = parseaddr(sender)
    email_addr = parsed[1] if len(parsed) == 2 else ""
    match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
    sender_domain = match.group(1).lower() if match else ""

    thread_id = msg["threadId"]
    label_ids = msg.get("labelIds", [])
    labels = ",".join(label_ids)  # raw IDs unless you re-add get_label_map()

    body = ""
    parts = msg["payload"].get("parts", [])
    for part in parts:
        mime_type = part.get("mimeType")
        data = part["body"].get("data")
        if not data:
            continue
        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        if mime_type == "text/plain":
            body = decoded.strip()
            break
        elif mime_type == "text/html" and not body:
            soup = BeautifulSoup(decoded, "html.parser")
            body = html.unescape(soup.get_text(separator=" ", strip=True))

    return {
        "thread_id": thread_id,
        "subject": subject,
        "body": body,
        "date": date_str,
        "timestamp": date_obj,
        "labels": labels,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sender": sender,
        "sender_domain": sender_domain,
        "parser_version": PARSER_VERSION,
    }


def extract_status_dates(body, received_date):
    """Extract key status dates from email body."""
    body_lower = body.lower()
    dates = {
        "response_date": "",
        "rejection_date": "",
        "interview_date": "",
        "follow_up_dates": "",
    }
    if any(p in body_lower for p in PATTERNS.get("response", [])):
        dates["response_date"] = received_date
    if any(p in body_lower for p in PATTERNS.get("rejection", [])):
        dates["rejection_date"] = received_date
    if any(p in body_lower for p in PATTERNS.get("interview", [])):
        dates["interview_date"] = received_date
    if any(p in body_lower for p in PATTERNS.get("follow_up", [])):
        dates["follow_up_dates"] = received_date
    return dates


def classify_message(body):
    """Classify message body into a status category based on patterns.json."""
    body_lower = body.lower()
    if any(p in body_lower for p in PATTERNS.get("rejection", [])):
        return "rejection"
    if any(p in body_lower for p in PATTERNS.get("interview", [])):
        return "interview"
    if any(p in body_lower for p in PATTERNS.get("follow_up", [])):
        return "follow_up"
    if any(p in body_lower for p in PATTERNS.get("application", [])):
        return "application"
    if any(p in body_lower for p in PATTERNS.get("response", [])):
        return "response"
    return ""


def parse_subject(subject, sender=None, sender_domain=None):
    """Extract company, job title, and job ID from subject line, sender, and optionally sender domain."""

    RESUME_NOISE_PATTERNS = [
        r"\bresume\b",
        r"\bcv\b",
        r"\bcover letter\b",
    ]

    # --- ML classification ---
    result = predict_subject_type(subject)
    label = result["label"]
    confidence = result["confidence"]
    ignore = result["ignore"]

    # --- Hard-ignore for resume or known noise patterns ---
    if label == "noise" or should_ignore(subject, "") or any(re.search(p, subject, re.I) for p in RESUME_NOISE_PATTERNS):
        return {
            "company": "",
            "job_title": "",
            "job_id": "",
            "predicted_company": "",
            "label": "noise",
            "confidence": 0.9,
            "ignore": True,
        }

    # --- Entity extraction ---
    entities = extract_entities(subject)
    company = entities.get("company", "")
    job_title = entities.get("job_title", "")
    job_id = ""

    # --- Continue with original logic for fallback or enrichment ---
    subject_clean = subject.strip()
    subj_lower = subject_clean.lower()
    domain_lower = sender_domain.lower() if sender_domain else None

    # Colon-prefix
    if not company:
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
            r"\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring)\b",
            "",
            display_name,
            flags=re.I,
        ).strip()
        if cleaned:
            company = cleaned

    # Regex patterns
    patterns = [
        (r"application (?:to|for|with)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"(?:from|with|at)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"^([A-Z][\w\s&\-]+)\s+(Job|Application|Interview)", 0),
        (r"-\s*([A-Z][\w\s&\-]+)\s*-\s*", 0),
        (r"^([A-Z][\w\s&\-]+)\s+application", 0),
        (r"(?:your application with|application with|interest in|position at)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"update on your ([A-Z][\w\s&\-]+) application", re.IGNORECASE),
        (r"thank you for your application with\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"@\s*([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"^([A-Z][\w\s&\-]+)\s+[-:]", re.IGNORECASE),  # catches "ECS -", "Partner Forces:"
    ]
    for pat, flags in patterns:
        if not company:
            match = re.search(pat, subject_clean, flags)
            if match:
                company = match.group(1).strip()

    # Job title fallback
    if not job_title:
        title_match = re.search(
            r"job\s+(?:submission\s+for|application\s+for|title\s+is)?\s*([\w\s\-]+)",
            subject_clean,
            re.IGNORECASE,
        )
        job_title = title_match.group(1).strip() if title_match else ""

    # Job ID
    id_match = re.search(
        r"(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)", subject_clean, re.IGNORECASE
    )
    job_id = id_match.group(1).strip() if id_match else ""

    return {
        "company": company,
        "job_title": job_title,
        "job_id": job_id,
        "predicted_company": company,
        "label": label,
        "confidence": confidence,
        "ignore": False,
    }

def ingest_message(service, msg_id):
    # ✅ Fetch stats lazily via helper, avoids DB access at import
    stats = get_stats()

    try:
        metadata = extract_metadata(service, msg_id)
        body = metadata["body"]
    except Exception as e:
        if DEBUG:
            print(f"❌ Failed to extract data for {msg_id}: {e}")
        return

    # Parse subject for initial extraction
    parsed_subject = (
        parse_subject(
            metadata["subject"],
            sender=metadata.get("sender"),
            sender_domain=metadata.get("sender_domain"),
        )
        or {}
    )

    # ✅ Respect ML ignore flag
    if parsed_subject.get("ignore"):
        if DEBUG:
            print(f"⚠️ Ignored by ML: {metadata['subject']}")
        log_ignored_message(
            msg_id, metadata, reason=parsed_subject.get("ignore_reason", "ml_ignore")
        )
        stats.total_ignored += 1
        stats.save()
        return "ignored"

    # ✅ Always classify and extract dates AFTER ignore check
    ### UPDATED: moved classification down here
    status = classify_message(body)
    status_dates = extract_status_dates(body, metadata["date"])

    if DEBUG:
        print(f"📥 Inserting message: {metadata['subject']}")

    # Store subject/body for ML training
    ### UPDATED: insert_email_text now only runs if not ignored
    insert_email_text(msg_id, metadata["subject"], body)

    # ✅ Skip if already ingested
    #if Message.objects.filter(msg_id=msg_id).exists():
    #    if DEBUG:
    #       print(f"⏩ Skipping already ingested: {msg_id}")
    #    stats.total_skipped += 1
    #    stats.save()
    #    return "skipped"

    subject = metadata["subject"]

    # ✅ Call subject/body classifier here
    result = predict_subject_type(subject, body)

    # ✅ Insert new message with classifier output
    Message.objects.create(
        msg_id=msg_id,
        thread_id=metadata["thread_id"],
        subject=subject,
        sender=metadata["sender"],
        body=metadata["body"],
        timestamp=metadata["timestamp"],
        ml_label=result["label"],  # classifier’s predicted label
        confidence=result["confidence"],  # classifier’s confidence
        reviewed=False,  # still available for manual review
    )
    stats.total_inserted += 1
    stats.save()

    # --- Company enrichment tiers ---
    company = parsed_subject.get("company", "") or ""
    company_norm = company.lower()
    company_source = "subject_parse"

    # Tier 1 & 2: whitelist / heuristic
    if company_norm not in KNOWN_COMPANIES and not is_valid_company(company):
        company = ""

    # Tier 3: domain mapping
    if not company:
        sender_domain = metadata.get("sender_domain", "").lower()
        mapped = DOMAIN_TO_COMPANY.get(sender_domain, "")
        if mapped:
            company = mapped
            company_source = "domain_mapping"
            if DEBUG:
                print(f"🧩 Domain mapping used: {sender_domain} → {company}")

    # Tier 3.5: sender name heuristic
    if not company:
        sender_name = metadata.get("sender", "").split("<")[0].strip().lower()
        for known in KNOWN_COMPANIES:
            if known.lower() in sender_name:
                company = known
                company_source = "sender_name_match"
                if DEBUG:
                    print(f"🔍 Sender name match: {sender_name} → {company}")
                break

    # Tier 4: ML fallback
    if not company:
        try:
            predicted = predict_company(subject, body)
            if predicted:
                company = predicted
                company_source = "ml_prediction"
                if DEBUG:
                    print(f"🧠 ML prediction used: {predicted}")
        except NameError:
            if DEBUG:
                print("⚠️ ML prediction function not available.")
            pass

    # Tier 5: body regex fallback
    if not company:
        body_match = re.search(
            r"(?:apply(?:ing)? to|application to|interest in|position at|role at|opportunity with)\s+([A-Z][\w\s&\-]+)",
            body,
            re.IGNORECASE
        )
        if body_match:
            company = body_match.group(1).strip()
            company_source = "body_regex"
            if DEBUG:
                print(f"📄 Body regex used: {company}")
                                    
    # Final record assembly
    record = {
        "thread_id": metadata["thread_id"],
        "company": company,
        "predicted_company": parsed_subject.get("predicted_company", ""),
        "job_title": parsed_subject.get("job_title", ""),
        "job_id": parsed_subject.get("job_id", ""),
        "first_sent": metadata["date"],
        "response_date": status_dates["response_date"],
        "follow_up_dates": status_dates["follow_up_dates"],
        "rejection_date": status_dates["rejection_date"],
        "interview_date": status_dates["interview_date"],
        "status": status,
        "labels": metadata["labels"],
        "subject": metadata["subject"],
        "sender": metadata["sender"],
        "sender_domain": metadata["sender_domain"],
        "last_updated": metadata["last_updated"],
        "company_source": company_source,
    }

    # 🚫 Drop messages with no extractable metadata
    if not record["company"] and not record["job_title"] and not record["job_id"]:
        if DEBUG:
            print(f"⚠️ Ignored due to empty metadata: {metadata['subject']}")
        log_ignored_message(msg_id, metadata, reason="empty_metadata")
        stats.total_ignored += 1
        stats.save()
        return "ignored"

    # Build composite index once, from cleaned company/job_title/job_id
    record["company_job_index"] = build_company_job_index(
        record.get("company", ""), record.get("job_title", ""), record.get("job_id", "")
    )

    if DEBUG:
        print(f"🔍 company: {record['company']}")
        print(f"🔍 job_title: {record['job_title']}")
        print(f"🔍 job_id: {record['job_id']}")
        print(f"🔍 company_source: {record['company_source']}")
        print(f"🔍 company_job_index: {record['company_job_index']}")

    if should_ignore(metadata["subject"], metadata["body"]):
        if DEBUG:
            print(f"⚠️ Ignored by pattern: {metadata['subject']}")
        log_ignored_message(msg_id, metadata, reason="pattern_ignore")
        stats.total_ignored += 1
        stats.save()
        return "ignored"
    #   
    # Insert or update application record in the database   
    insert_or_update_application(record)
    
    if DEBUG:
        print(f"✅ Logged: {metadata['subject']}")

    return "inserted"
