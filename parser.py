# parser.py
import os
import re
import json
import base64
import html
import joblib

# from joblib import load  # not needed here
import quopri
import django
from django.utils import timezone
from django.utils.timezone import now
from django.db.models import F
from pathlib import Path
from email.utils import parsedate_to_datetime, parseaddr
from bs4 import BeautifulSoup
from db import (
    insert_email_text,
    insert_or_update_application,
    is_valid_company,
    PATTERNS_PATH,
    COMPANIES_PATH,
)
from datetime import datetime, timedelta
from db_helpers import get_application_by_sender, build_company_job_index
from ml_subject_classifier import predict_subject_type
from ml_entity_extraction import extract_entities
from tracker.models import (
    Application,
    Message,
    IgnoredMessage,
    IngestionStats,
    Company,
    UnresolvedCompany,
)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()
DEBUG = True

# --- Load patterns.json ---
if PATTERNS_PATH.exists():
    with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
        patterns_data = json.load(f)
    PATTERNS = patterns_data
else:
    PATTERNS = {}
# Map from label names used in code to JSON keys
LABEL_MAP = {
    "interview_invite": ["interview", "interview_invite"],
    "job_application": ["application", "job_application"],
    "rejected": ["rejection", "rejected"],
    "offer": ["offer"],
    "noise": ["noise"],
    "ignore": ["ignore"],
    "response": ["response"],
    "follow_up": ["follow_up"],
    "ghosted": ["ghosted"],
    "referral": ["referral"],
    "head_hunter": ["head_hunter"],
}

_MSG_LABEL_PATTERNS = {}
for code_label, json_keys in LABEL_MAP.items():
    patterns = []
    # Try message_labels first (new structure)
    if "message_labels" in PATTERNS:
        for key in json_keys:
            if key in PATTERNS["message_labels"]:
                pattern_list = PATTERNS["message_labels"][key]
                if isinstance(pattern_list, list):
                    patterns.extend(pattern_list)
                elif isinstance(pattern_list, str):
                    patterns.append(pattern_list)
    # Fall back to top-level keys (legacy structure)
    if not patterns:
        for key in json_keys:
            if key in PATTERNS:
                pattern_list = PATTERNS[key]
                if isinstance(pattern_list, list):
                    patterns.extend(pattern_list)
                elif isinstance(pattern_list, str):
                    patterns.append(pattern_list)

    # Compile patterns, skip "None"
    compiled = []
    for p in patterns:
        if p != "None":
            try:
                compiled.append(re.compile(p, re.I))
            except re.error as e:
                print(f"⚠️  Invalid regex pattern for {code_label}: {p} - {e}")
    _MSG_LABEL_PATTERNS[code_label] = compiled

# Optional per-label negative patterns derived from Gmail's doesNotHaveTheWord
_MSG_LABEL_EXCLUDES = {
    k: [
        re.compile(p, re.I)
        for p in PATTERNS.get("message_label_excludes", {}).get(k, [])
    ]
    for k in (
        "interview_invite",
        "job_application",
        "rejected",
        "offer",
        "noise",
        "ignore",
        "response",
        "follow_up",
        "ghosted",
        "referral",
    )
}


def rule_label(subject: str, body: str = "") -> str | None:
    s = f"{subject or ''} {body or ''}"
    # Check labels in priority order (most specific → least specific)
    # Rejection before application: catches "received application BUT unfortunately..."
    # Interview before application: catches action-oriented "next steps"
    # Application last: generic catch-all for confirmations
    for label in (
        "offer",  # Most specific: offer, compensation, package
        "rejected",  # Specific negatives: unfortunately, other candidates
        "interview_invite",  # Action-oriented: schedule, availability, interview
        "job_application",  # Generic: received, thank you, will be reviewed
        "referral",  # Referral/intro messages
        "head_hunter",  # Recruiter blasts
        "noise",  # Generic promos, OTPs, newsletters (often matched by body/footer)
        "ghosted",
        "blank",
    ):
        for rx in _MSG_LABEL_PATTERNS.get(label, []):
            if rx.search(s):
                # If any exclude pattern matches, skip this label
                excludes = _MSG_LABEL_EXCLUDES.get(label, [])
                if any(ex.search(s) for ex in excludes):
                    continue
                return label
    return None


def predict_with_fallback(
    predict_subject_type_fn, subject: str, body: str = "", threshold: float = 0.55
):
    """
    Wrap ML predictor; if low confidence or empty features, fall back to rules.
    Expects ML to return dict with keys: label, confidence (or proba).
    """
    ml = predict_subject_type_fn(subject, body)
    conf = float(ml.get("confidence", ml.get("proba", 0.0)) if ml else 0.0)
    if not ml or conf < threshold:
        rl = rule_label(subject, body)
        if rl:
            return {"label": rl, "confidence": conf, "fallback": "rules"}
    if ml and "confidence" not in ml and "proba" in ml:
        ml = {**ml, "confidence": float(ml["proba"])}
    return ml


# def strip_html_tags(text: str) -> str:
#    if not text:
#        return "Empty"
#    # BeautifulSoup handles nested tags, entities, script/style removal better than regex
#    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def get_stats():
    today = now().date()
    stats, _ = IngestionStats.objects.get_or_create(date=today)
    return stats


def decode_part(data, encoding):
    if encoding == "base64":
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    elif encoding == "quoted-printable":
        return quopri.decodestring(data).decode("utf-8", errors="ignore")
    elif encoding == "7bit":
        return data  # usually already decoded
    else:
        return data


# def extract_body(payload):
#    """Best-effort plain-text body extraction for simple payloads."""
##    if "parts" in payload:
#        for part in payload["parts"]:
#            mt = part.get("mimeType")
#            data = part.get("body", {}).get("data")
#            if not data:
#               continue
#            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
#            if mt == "text/plain":
#                return decoded
#            if mt == "text/html":
#                return strip_html_tags(decoded)
#    data = payload.get("body", {}).get("data")
#    return (
#        base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore") if data else ""
#    )


def extract_body_from_parts(parts):
    for part in parts:
        mime_type = part.get("mimeType")
        body_data = part.get("body", {}).get("data")
        if mime_type == "text/html" and body_data:
            decoded = base64.urlsafe_b64decode(body_data).decode(
                "utf-8", errors="ignore"
            )
            if not decoded:
                decoded = "Empty Body"
                print("Decoded Body/HTML part is empty.")
            return decoded  # preserve full HTML
        elif "parts" in part:
            result = extract_body_from_parts(part["parts"])
            if result:
                return result
            else:
                return "Empty Body"
    return ""


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


def is_valid_company_name(name):
    """Reject company names that match known invalid prefixes from patterns.json."""
    if not name:
        return False

    invalid_prefixes = PATTERNS.get("invalid_company_prefixes", [])
    for prefix in invalid_prefixes:
        try:
            # Compile each prefix as regex, using re.IGNORECASE
            if re.match(prefix, name, re.IGNORECASE):
                return False
        except re.error:
            # If invalid regex, fallback to simple startswith
            if name.lower().startswith(prefix.lower()):
                return False
    return True


PARSER_VERSION = "1.0.0"

# --- Optional local ML artifact load (parser-local). Actual classification is handled in ml_subject_classifier. ---
MODEL_DIR = Path(__file__).parent / "model"
_MODEL_PATH = MODEL_DIR / "message_classifier.pkl"
_SUBJ_VEC_PATH = MODEL_DIR / "subject_vectorizer.pkl"
_BODY_VEC_PATH = MODEL_DIR / "body_vectorizer.pkl"
_LABELS_PATH = MODEL_DIR / "message_label_encoder.pkl"

# Optional company-level classifier artifacts (if present)
_COMP_MODEL_PATH = MODEL_DIR / "company_classifier.pkl"
_COMP_VEC_PATH = MODEL_DIR / "vectorizer.pkl"
_COMP_LABELS_PATH = MODEL_DIR / "label_encoder.pkl"

CLASSIFIER = None
SUBJECT_VECTORIZER = None
BODY_VECTORIZER = None
LABEL_ENCODER = None
ml_enabled = False

# Company classifier handles company name prediction (optional)
COMPANY_CLASSIFIER = None
COMPANY_VECTORIZER = None
COMPANY_LABEL_ENCODER = None

if (
    _MODEL_PATH.exists()
    and _SUBJ_VEC_PATH.exists()
    and _BODY_VEC_PATH.exists()
    and _LABELS_PATH.exists()
):
    try:
        CLASSIFIER = joblib.load(_MODEL_PATH)
        SUBJECT_VECTORIZER = joblib.load(_SUBJ_VEC_PATH)
        BODY_VECTORIZER = joblib.load(_BODY_VEC_PATH)
        LABEL_ENCODER = joblib.load(_LABELS_PATH)
        ml_enabled = True
        if DEBUG:
            print("🤖 Parser: local ML artifacts loaded (optional).")
    except Exception as _e:
        # Non-fatal: ml_subject_classifier handles predictions; keep quiet to avoid confusing logs
        CLASSIFIER = None
        SUBJECT_VECTORIZER = None
        BODY_VECTORIZER = None
        LABEL_ENCODER = None
        ml_enabled = False
else:
    # Artifacts missing locally; this is fine since ml_subject_classifier is authoritative.
    # Do not print a warning to avoid noise during management commands.
    ml_enabled = False

# Load optional company classifier artifacts (non-fatal if missing)
if _COMP_MODEL_PATH.exists() and _COMP_VEC_PATH.exists() and _COMP_LABELS_PATH.exists():
    try:
        COMPANY_CLASSIFIER = joblib.load(_COMP_MODEL_PATH)
        COMPANY_VECTORIZER = joblib.load(_COMP_VEC_PATH)
        COMPANY_LABEL_ENCODER = joblib.load(_COMP_LABELS_PATH)
        if DEBUG:
            print("🤖 Parser: company classifier artifacts loaded (optional).")
    except Exception:
        COMPANY_CLASSIFIER = None
        COMPANY_VECTORIZER = None
        COMPANY_LABEL_ENCODER = None


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
    # Use optional company-specific classifier if available; otherwise skip
    if not (COMPANY_CLASSIFIER and COMPANY_VECTORIZER):
        return None
    text = (subject or "") + " " + (body or "")
    try:
        X = COMPANY_VECTORIZER.transform([text])
        pred = COMPANY_CLASSIFIER.predict(X)[0]
        if COMPANY_LABEL_ENCODER is not None and hasattr(
            COMPANY_LABEL_ENCODER, "inverse_transform"
        ):
            try:
                return COMPANY_LABEL_ENCODER.inverse_transform([pred])[0]
            except Exception:
                pass
        # Fallback to string conversion
        return str(pred)
    except Exception:
        return None


def should_ignore(subject, body):
    """Return True if subject/body matches ignore patterns."""
    subj_lower = subject.lower()
    ignore_patterns = PATTERNS.get("ignore", [])
    return any(p.lower() in subj_lower for p in ignore_patterns)


def extract_metadata(service, msg_id):
    body_html = ""
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
    body = extract_body_from_parts(parts)

    for part in parts:
        mime_type = part.get("mimeType")
        data = part["body"].get("data")
        if not data:
            continue
        # decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        encoding = part.get("body", {}).get("encoding", "base64").lower()
        data = part.get("body", {}).get("data")
        if data:
            decoded = decode_part(data, encoding)

        if mime_type == "text/plain" and body == "Empty Body":
            body = decoded.strip()
        elif mime_type == "text/html" and body != "Empty Body":
            body_html = html.unescape(decoded)
            # also provide a plain-text fallback
            body = BeautifulSoup(body_html, "html.parser").get_text(
                separator=" ", strip=True
            )

    # Fallback if no parts
    if not body and "body" in msg["payload"]:
        data = msg["payload"]["body"].get("data")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    return {
        "thread_id": thread_id,
        "subject": subject,
        "body": body,
        "body_html": body_html,
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
        "response_date": None,
        "rejection_date": None,
        "interview_date": None,
        "follow_up_dates": [],
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
        return "rejected"
    if any(p in body_lower for p in PATTERNS.get("interview", [])):
        return "interview_invite"
    if any(p in body_lower for p in PATTERNS.get("follow_up", [])):
        return "follow_up"
    if any(p in body_lower for p in PATTERNS.get("application", [])):
        return "job_application"
    if any(p in body_lower for p in PATTERNS.get("response", [])):
        return "response"
    # removed job_alert label
    return ""


def parse_subject(subject, body="", sender=None, sender_domain=None):
    """Extract company, job title, and job ID from subject line, sender, and optionally sender domain."""

    if DEBUG:
        print(f"[DEBUG] parse_subject called with:")
        print(f"[DEBUG]   subject={subject[:60]}...")
        print(f"[DEBUG]   sender={sender}")
        print(f"[DEBUG]   sender_domain={sender_domain}")

    RESUME_NOISE_PATTERNS = [
        r"\bresume\b",
        r"\bcv\b",
        r"\bcover letter\b",
        r"\bmuch more\b",
        r"\bnow available\b",
        r"\bgift card\b",
        r"\bcyberattack\b",
    ]

    # --- ML classification ---
    # Use ML with rule fallback
    result = predict_with_fallback(predict_subject_type, subject, body, threshold=0.55)
    confidence = _conf(result)
    label = result["label"]
    ignore = bool(result.get("ignore", False))

    print("=== PARSE_SUBJECT CALLED ===", flush=True)
    print(f"DEBUG={DEBUG}", flush=True)
    if DEBUG:
        print(f"[DEBUG parse_subject] subject='{subject[:80]}'", flush=True)
        print(f"[DEBUG parse_subject] sender='{sender}'", flush=True)
        print(f"[DEBUG parse_subject] sender_domain='{sender_domain}'", flush=True)
        print(
            f"[DEBUG parse_subject] label={label}, confidence={confidence}", flush=True
        )

    # --- Initialize variables ---
    company = ""
    job_title = ""
    job_id = ""

    # --- Continue with original logic for fallback or enrichment ---
    subject_clean = subject.strip()
    # Strip common email reply/forward prefixes that interfere with company extraction
    subject_clean = re.sub(
        r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject_clean, flags=re.IGNORECASE
    ).strip()
    subj_lower = subject_clean.lower()
    domain_lower = sender_domain.lower() if sender_domain else None

    # PRIORITY 1: ATS domain with known sender prefix (most reliable)
    if not company and domain_lower in ATS_DOMAINS and sender:
        # First try to extract from sender email prefix (e.g., ngc@myworkday.com)
        if "@" in sender:
            sender_prefix = sender.split("@")[0].strip().lower()
            # Check if prefix matches an alias
            aliases_lower = {
                k.lower(): v for k, v in company_data.get("aliases", {}).items()
            }
            if sender_prefix in aliases_lower:
                company = aliases_lower[sender_prefix]
                if DEBUG:
                    print(f"[DEBUG] ATS alias match: {sender_prefix} -> {company}")

        # Fallback to display name extraction
        if not company:
            display_name, _ = parseaddr(sender)
            cleaned = re.sub(
                r"\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring)\b",
                "",
                display_name,
                flags=re.I,
            ).strip()
            if cleaned:
                company = cleaned
                if DEBUG:
                    print(f"[DEBUG] ATS display name: {company}")

    # PRIORITY 2: Domain mapping (direct company domains)
    if not company and domain_lower and domain_lower in DOMAIN_TO_COMPANY:
        company = DOMAIN_TO_COMPANY[domain_lower]

    # PRIORITY 3: Known companies in subject
    if not company and KNOWN_COMPANIES:
        # Sort by length descending to match "Northrop Grumman" before "Northrop"
        sorted_companies = sorted(KNOWN_COMPANIES, key=len, reverse=True)
        for known in sorted_companies:
            if known in subj_lower:
                # Find original casing from known list
                for orig in company_data.get("known", []):
                    if orig.lower() == known:
                        company = orig
                        break
                if not company:  # fallback to title case
                    company = known.title()
                break

    # PRIORITY 4: Entity extraction (spaCy NER)
    if not company:
        entities = extract_entities(subject)
        company = entities.get("company", "")
        if not job_title:
            job_title = entities.get("job_title", "")

    # PRIORITY 5: Colon-prefix pattern
    if not company:
        m = re.match(r"^([A-Z][A-Za-z0-9&.\- ]+):", subject_clean)
        if m:
            company = m.group(1).strip()

    # PRIORITY 6: Regex patterns
    patterns = [
        (r"application (?:to|for|with)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"(?:from|with|at)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (
            r"position\s+@\s+([A-Z][\w\s&\-]+)",
            re.IGNORECASE,
        ),  # catches "position @ Claroty",
        (r"^([A-Z][\w\s&\-]+)\s+(Job|Application|Interview)", 0),
        (r"-\s*([A-Z][\w\s&\-]+)\s*-\s*", 0),
        (r"^([A-Z][\w\s&\-]+)\s+application", 0),
        (
            r"(?:your application with|application with|interest in|position at)\s+([A-Z][\w\s&\-]+)",
            re.IGNORECASE,
        ),
        (r"update on your ([A-Z][\w\s&\-]+) application", re.IGNORECASE),
        (r"thank you for your application with\s+([A-Z][\w\s&\-]+)", re.IGNORECASE),
        (r"@\s*([A-Z][\w\s&\-]+)", re.IGNORECASE),
        # Removed the problematic pattern that was matching "Re:" - now handled by prefix stripping above
        (
            r"applying for ([\w\s\-]+) position @ ([A-Z][\w\s&\-]+)",
            re.IGNORECASE,
        ),  # special case
    ]
    # Handle special case: "applying for Field CTO position @ Claroty"
    special_match = re.search(
        r"applying for ([\w\s\-]+) position @ ([A-Z][\w\s&\-]+)", subject_clean
    )
    if special_match:
        job_title = special_match.group(1).strip()
        company = special_match.group(2).strip()

    for pat, flags in patterns:
        if not company:
            match = re.search(pat, subject_clean, flags)
            if match:
                company = match.group(1).strip()

    # 🧼 Sanity check: reject job titles misclassified as companies
    if company and re.search(
        r"\b(CTO|Engineer|Manager|Director|Intern|Analyst)\b", company, re.I
    ):
        company = ""

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

    # --- Hard-ignore check AFTER company extraction ---
    # If we found a valid company from known list or domain, override noise classification
    if company and (
        (domain_lower and domain_lower in DOMAIN_TO_COMPANY)
        or (subj_lower and any(known in subj_lower for known in KNOWN_COMPANIES))
    ):
        # Valid company detected, not noise - reclassify if needed
        if label == "noise":
            label = "job_application"  # assume application if company found
            confidence = 0.7  # moderate confidence for overridden classification

    # Hard-ignore for resume or known noise patterns (only if no valid company)
    if not company and (
        label == "noise"
        or should_ignore(subject, "")
        or any(re.search(p, subject, re.I) for p in RESUME_NOISE_PATTERNS)
    ):
        return {
            "company": "",
            "job_title": "",
            "job_id": "",
            "predicted_company": "",
            "label": "noise",
            "confidence": 0.9,
            "ignore": True,
        }

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
    stats = get_stats()

    try:
        metadata = extract_metadata(service, msg_id)
        body = metadata["body"]
        result = None  #  Prevent UnboundLocalError

        # --- PATCH: Skip and log blank/whitespace-only bodies ---
        if not body or not body.strip():
            if DEBUG:
                print(
                    f"[BLANK BODY] Skipping message {msg_id}: {metadata.get('subject','(no subject)')}"
                )
                print("Stats: ignored++ (blank body)")
            log_ignored_message(msg_id, metadata, reason="blank_body")
            IngestionStats.objects.filter(date=stats.date).update(
                total_ignored=F("total_ignored") + 1
            )
            return "ignored"

    except Exception as e:
        if DEBUG:
            print(f"Failed to extract data for {msg_id}: {e}")
        return

    parsed_subject = (
        parse_subject(
            metadata["subject"],
            metadata.get("body", ""),
            sender=metadata.get("sender"),
            sender_domain=metadata.get("sender_domain"),
        )
        or {}
    )

    if parsed_subject.get("ignore"):
        if DEBUG:
            print(f"Ignored by ML: {metadata['subject']}")
            print("Stats: ignored++ (ML ignore)")
        log_ignored_message(
            msg_id,
            metadata,
            reason=parsed_subject.get("ignore_reason", "ml_ignore"),
        )
        IngestionStats.objects.filter(date=stats.date).update(
            total_ignored=F("total_ignored") + 1
        )
        return "ignored"

    status = classify_message(body)
    status_dates = extract_status_dates(body, metadata["date"])

    def to_date(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date()
        except Exception:
            return None

    status_dates = {
        "response_date": to_date(status_dates.get("response_date")),
        "rejection_date": to_date(status_dates.get("rejection_date")),
        "interview_date": to_date(status_dates.get("interview_date")),
        "follow_up_dates": status_dates.get("follow_up_dates", []),
    }

    # Normalize follow_up_dates and labels to strings
    follow_up_raw = status_dates.get("follow_up_dates", [])
    follow_up_str = (
        ", ".join(follow_up_raw)
        if isinstance(follow_up_raw, list)
        else str(follow_up_raw)
    )

    labels_raw = metadata.get("labels", [])
    labels_str = (
        ", ".join(labels_raw) if isinstance(labels_raw, list) else str(labels_raw)
    )

    if DEBUG:
        print(f"Inserting message: {metadata['subject']}")

    insert_email_text(msg_id, metadata["subject"], body)

    subject = metadata["subject"]
    result = predict_subject_type(subject, body)

    # --- NEW LOGIC: Robust company extraction order ---
    # Add guard: skip company assignment for noise label
    label_guard = result.get("label") if result else None
    skip_company_assignment = label_guard == "noise"
    company = ""
    company_source = ""
    company_obj = None
    if not skip_company_assignment:
        sender_domain = metadata.get("sender_domain", "").lower()
        is_ats = any(d in sender_domain for d in ATS_DOMAINS)

        # 1. Domain mapping (if not ATS)
        if sender_domain and not is_ats and sender_domain in DOMAIN_TO_COMPANY:
            company = DOMAIN_TO_COMPANY[sender_domain]
            company_source = "domain_mapping"
            if DEBUG:
                print(f"Domain mapping used: {sender_domain} → {company}")

        # 2. Subject/body parse (if not resolved by domain)
        if not company:
            parsed_company = parsed_subject.get("company", "") or ""
            if parsed_company and is_valid_company_name(parsed_company):
                company = parsed_company
                company_source = "subject_parse"
                if DEBUG:
                    print(f"Subject/body parse used: {company}")

        # 3. ML/NER extraction (if still unresolved)
        if not company:
            try:
                predicted = predict_company(subject, body)
                if (
                    predicted
                    and predicted.lower() not in {"job_application", "noise"}
                    and is_valid_company_name(predicted)
                ):
                    company = predicted
                    company_source = "ml_prediction"
                    if DEBUG:
                        print(f"ML prediction used: {predicted}")
            except NameError:
                if DEBUG:
                    print(" ML prediction function not available.")

        # 4. Regex/body fallback (if still unresolved)
        if not company:
            at_match = re.search(
                r"@\s*([A-Za-z][\w\s&\-]+?)(?=[\W]|$)", body, flags=re.IGNORECASE
            )
            if at_match:
                company = at_match.group(1).strip().title()
                company_source = "body_at_symbol"
                if DEBUG:
                    print(f"'@' symbol match used: {company}")

        if not company:
            body_match = re.search(
                r"(?:apply(?:ing)? to|application to|interest in|position at|role at|opportunity with)\s+([A-Z][\w\s&\-]+)",
                body,
                re.IGNORECASE,
            )
            if body_match:
                company = body_match.group(1).strip()
                company_source = "body_regex"
                if DEBUG:
                    print(f" Body regex used: {company}")

        # 5. Sender name fallback (rare, last resort)
        if not company:
            sender_name = metadata.get("sender", "").split("<")[0].strip().lower()
            for known in KNOWN_COMPANIES:
                if known.lower() in sender_name:
                    company = known
                    company_source = "sender_name_match"
                    if DEBUG:
                        print(f" Sender name match: {sender_name} → {company}")
                    break

        # 6. Final fallback
        if not company:
            company_source = "unresolved"

        # Normalize casing for known companies
        if company:
            for known in KNOWN_COMPANIES:
                if company.lower() == known.lower():
                    company = known
                    break
        # Sanity check: does subject contain a conflicting company name?
        subject_lower = metadata["subject"].lower()
        if company and company.lower() not in subject_lower:
            for known in KNOWN_COMPANIES:
                if known.lower() in subject_lower and known.lower() != company.lower():
                    print(
                        f"Subject mentions different company: {known} vs resolved {company}"
                    )
                    break

    confidence = float(result.get("confidence", 0.0)) if result else 0.0

    if company:
        company_obj, _ = Company.objects.get_or_create(
            name=company,
            defaults={
                "first_contact": metadata["timestamp"],
                "last_contact": metadata["timestamp"],
                "confidence": confidence,
            },
        )
        if company_obj and not company_obj.domain:
            sender_domain = metadata.get("sender_domain", "").lower()
            if sender_domain:
                company_obj.domain = sender_domain
                company_obj.save()
                if DEBUG:
                    print(f"Set domain for {company}: {sender_domain}")

    if DEBUG:
        confidence = result.get("confidence", 0.0) if result else 0.0
        print(f"Final company: {company}")
        print(f"company_obj: {company_obj}")
        print(f"ML label: {result.get('label') if result else 'unknown'}")
        print(f"confidence: {confidence}")

    #
    # This is the re-ingest logic
    #
    #  Skip logic (now safe to run after enrichment)
    existing = Message.objects.filter(msg_id=msg_id).first()
    if existing:
        if DEBUG:
            print(f"Updating existing message: {msg_id}")
            print(f"Stats: skipped++ (re-ingest)")
        if company_obj:
            existing.company = company_obj
            existing.company_source = company_source
        if result:
            existing.ml_label = result["label"]
            existing.confidence = result["confidence"]
        if (
            result
            and result.get("confidence", 0.0) >= 0.85
            and result.get("label") != "noise"
            and company_obj is not None
            and is_valid_company(company)
        ):
            existing.reviewed = True
        existing.save()

        # ✅ Also update Application record during re-ingestion if dates are missing
        ml_label = result.get("label") if result else None
        if company_obj and ml_label:
            try:
                app = Application.objects.filter(
                    thread_id=metadata["thread_id"]
                ).first()
                if DEBUG:
                    print(
                        f"[Re-ingest] Looking for Application with thread_id={metadata['thread_id']}, found: {app is not None}"
                    )
                if app:
                    if DEBUG:
                        print(
                            f"[Re-ingest] App ml_label={app.ml_label}, rejection_date={app.rejection_date}, ml_label_param={ml_label}"
                        )
                    updated = False
                    if not app.rejection_date and ml_label == "rejected":
                        app.rejection_date = metadata["timestamp"].date()
                        updated = True
                        if DEBUG:
                            print(
                                f"✓ Set rejection_date during re-ingest: {app.rejection_date}"
                            )
                    if not app.interview_date and ml_label == "interview_invite":
                        app.interview_date = metadata["timestamp"].date()
                        updated = True
                        if DEBUG:
                            print(
                                f"✓ Set interview_date during re-ingest: {app.interview_date}"
                            )
                    if not app.ml_label or app.ml_label != ml_label:
                        app.ml_label = ml_label
                        app.ml_confidence = (
                            float(result.get("confidence", 0.0)) if result else 0.0
                        )
                        updated = True
                    if updated:
                        app.save()
                        if DEBUG:
                            print(f"✓ Updated Application during re-ingest")
                else:
                    if DEBUG:
                        print(
                            f"[Re-ingest] No Application found for thread_id={metadata['thread_id']}"
                        )
            except Exception as e:
                if DEBUG:
                    print(
                        f"Warning: Could not update Application during re-ingest: {e}"
                    )

        IngestionStats.objects.filter(date=stats.date).update(
            total_skipped=F("total_skipped") + 1
        )
        return "skipped"

    reviewed = (
        result
        and result.get("confidence", 0.0) >= 0.85
        and result.get("label") != "noise"
        and company_obj is not None
        and is_valid_company(company)
    )
    # or whatever threshold you trust
    if DEBUG and not reviewed:
        print(
            f"Not reviewed: confidence={result.get('confidence', 0.0):.2f}, label={result.get('label')}, company={company}"
        )

    # ✅ Now safe to insert Message with enriched company
    Message.objects.create(
        msg_id=msg_id,
        thread_id=metadata["thread_id"],
        subject=subject,
        sender=metadata["sender"],
        body=metadata["body"],
        body_html=metadata["body_html"],
        timestamp=metadata["timestamp"],
        ml_label=result["label"],
        confidence=result["confidence"],
        reviewed=(reviewed),
        company=company_obj,
        company_source=company_source,
    )
    # ✅ Create or update Application record using Django ORM

    # ✅ Fallback: if pattern-based extraction didn't find rejection/interview dates,
    # but ML classified it as rejected/interview_invite, use message timestamp
    ml_label = result.get("label") if result else None
    rejection_date_final = status_dates["rejection_date"]
    interview_date_final = status_dates["interview_date"]

    if not rejection_date_final and ml_label == "rejected":
        rejection_date_final = metadata["timestamp"].date()
        if DEBUG:
            print(f"✓ Set rejection_date from ML label: {rejection_date_final}")

    if not interview_date_final and ml_label == "interview_invite":
        interview_date_final = metadata["timestamp"].date()
        if DEBUG:
            print(f"✓ Set interview_date from ML label: {interview_date_final}")

    try:
        message_obj = Message.objects.get(msg_id=msg_id)
        if company_obj and message_obj:
            application_obj, created = Application.objects.get_or_create(
                thread_id=metadata["thread_id"],
                defaults={
                    "company": company_obj,
                    "company_source": company_source,
                    "job_title": parsed_subject.get("job_title", ""),
                    "job_id": parsed_subject.get("job_id", ""),
                    "status": status,
                    "sent_date": metadata["timestamp"].date(),
                    "rejection_date": rejection_date_final,
                    "interview_date": interview_date_final,
                    "ml_label": ml_label,
                    "ml_confidence": (
                        float(result.get("confidence", 0.0)) if result else 0.0
                    ),
                    "reviewed": reviewed,
                },
            )

            # ✅ Update existing application if dates are missing but ML classified it
            if not created:
                updated = False
                if not application_obj.rejection_date and ml_label == "rejected":
                    application_obj.rejection_date = rejection_date_final
                    updated = True
                if (
                    not application_obj.interview_date
                    and ml_label == "interview_invite"
                ):
                    application_obj.interview_date = interview_date_final
                    updated = True
                if updated:
                    application_obj.save()
                    if DEBUG:
                        print(f"✓ Updated existing application with ML-derived dates")
            if created:
                if DEBUG:
                    print("Stats: inserted++ (new application)")
                IngestionStats.objects.filter(date=stats.date).update(
                    total_inserted=F("total_inserted") + 1
                )
            else:
                if DEBUG:
                    print("Stats: ignored++ (duplicate application)")
                IngestionStats.objects.filter(date=stats.date).update(
                    total_ignored=F("total_ignored") + 1
                )
        else:
            if DEBUG:
                print("Stats: skipped++ (missing company/message)")
            IngestionStats.objects.filter(date=stats.date).update(
                total_skipped=F("total_skipped") + 1
            )

    except Exception as e:
        if DEBUG:
            print(f"Failed to create Application: {e}")
        IngestionStats.objects.filter(date=stats.date).update(
            total_skipped=F("total_skipped") + 1
        )

    # Refresh stats before printing
    if DEBUG:
        stats.refresh_from_db()
        print(
            f"Stats updated: inserted={stats.total_inserted}, ignored={stats.total_ignored}, skipped={stats.total_skipped}"
        )

    # Final record assembly for applications table
    record = {
        "thread_id": metadata["thread_id"],
        "company": company,
        "predicted_company": parsed_subject.get("predicted_company", ""),
        "job_title": parsed_subject.get("job_title", ""),
        "job_id": parsed_subject.get("job_id", ""),
        "first_sent": metadata["date"],
        "response_date": status_dates["response_date"],
        "follow_up_dates": follow_up_str,
        "rejection_date": status_dates["rejection_date"],
        "interview_date": status_dates["interview_date"],
        "status": status,
        "labels": labels_str,
        "subject": metadata["subject"],
        "sender": metadata["sender"],
        "sender_domain": metadata["sender_domain"],
        "last_updated": metadata["last_updated"],
        "company_source": company_source,
    }
    if not company and not should_ignore(subject, body):
        UnresolvedCompany.objects.update_or_create(
            msg_id=msg_id,
            defaults={
                "subject": metadata["subject"],
                "body": metadata["body"],
                "sender": metadata["sender"],
                "sender_domain": metadata["sender_domain"],
                "timestamp": metadata["timestamp"],
            },
        )
        if DEBUG:
            print(f"Logged unresolved company for manual review: {msg_id}")

    if not record["company"] and not record["job_title"] and not record["job_id"]:
        reason = "unclassified"
        if not metadata["body"]:
            reason = "missing_body"
        elif metadata["body"] and not record["company"]:
            reason = "missing_company"
        if DEBUG:
            print(f"Ignored due to: {reason} -> {metadata['subject']}")
            print("Stats: ignored++ (unclassified)")
        log_ignored_message(msg_id, metadata, reason=reason)
        IngestionStats.objects.filter(date=stats.date).update(
            total_ignored=F("total_ignored") + 1
        )
        return "ignored"

    record["company_job_index"] = build_company_job_index(
        record.get("company", ""), record.get("job_title", ""), record.get("job_id", "")
    )

    if DEBUG:
        print(f"company: {record['company']}")
        print(f"job_title: {record['job_title']}")
        print(f"job_id: {record['job_id']}")
        print(f"company_source: {record['company_source']}")
        print(f"company_job_index: {record['company_job_index']}")

    if should_ignore(metadata["subject"], metadata["body"]):
        if DEBUG:
            print(f"Ignored by pattern: {metadata['subject']}")
            print("Stats: ignored++ (pattern ignore)")
        log_ignored_message(msg_id, metadata, reason="pattern_ignore")
        IngestionStats.objects.filter(date=stats.date).update(
            total_ignored=F("total_ignored") + 1
        )
        return "ignored"

    insert_or_update_application(record)

    if DEBUG:
        print(f"Logged: {metadata['subject']}")

    return "inserted"


COMPANIES_PATH = Path(__file__).parent / "json" / "companies.json"

if COMPANIES_PATH.exists():
    try:
        with open(COMPANIES_PATH, "r", encoding="utf-8") as f:
            company_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[Error] Failed to parse companies.json: {e}")
        company_data = {}
    except Exception as e:
        print(f"[Error] Unable to read companies.json: {e}")
        company_data = {}
    ATS_DOMAINS = [d.lower() for d in company_data.get("ats_domains", [])]
    KNOWN_COMPANIES = {c.lower() for c in company_data.get("known", [])}
    DOMAIN_TO_COMPANY = {
        k.lower(): v for k, v in company_data.get("domain_to_company", {}).items()
    }
    ALIASES = company_data.get("aliases", {})
else:
    ATS_DOMAINS = []
    KNOWN_COMPANIES = set()
    DOMAIN_TO_COMPANY = {}
    ALIASES = {}


def _conf(res) -> float:
    if not res:
        return 0.0
    try:
        return float(res.get("confidence", res.get("proba", 0.0)))
    except Exception:
        return 0.0
