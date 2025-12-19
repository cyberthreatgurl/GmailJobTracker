#!/usr/bin/env python3
"""Ingest a local .eml file into the app database as a Message (user upload).

Requirements:
- The uploaded file must contain standard headers including: Message-ID, From, To, Date, Subject.
- If headers are missing, the script aborts with an error.

Behavior:
- Parses the .eml file using the stdlib `email` package.
- Maps the message to a Company using heuristics:
  1) domain -> `json/companies.json` mapping
  2) exact known-company name in From/display-name or Subject
  3) fallback: leave company null
- Attempts to assign thread_id by matching an existing Message with the same subject+company.
  If none found, sets thread_id = message-id (sanitized).
- By default runs in dry-run mode (no DB writes). Use `--apply` to persist.
- Optionally create a ThreadTracking record for the thread with `--create-tt`.

Usage:
    python scripts/ingest_eml.py --file "C:\\path\\to\\message.eml" --dry-run
    python scripts/ingest_eml.py --file "..." --apply --create-tt --yes
"""

import os
import sys
import json
import argparse
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, parseaddr

# Setup Django
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django
from django.utils import timezone

django.setup()

from tracker.models import Company, Message, ThreadTracking, UnresolvedCompany

# Use existing parser + classifier so uploads follow same parsing path as re-ingest
try:
    from parser import parse_raw_message, predict_with_fallback, extract_status_dates
    from ml_subject_classifier import predict_subject_type
except Exception as e:
    import traceback

    print(f"WARNING: Failed to import classification functions: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    parse_raw_message = None
    predict_with_fallback = None
    predict_subject_type = None
    extract_status_dates = None

COMPANIES_JSON = os.path.join(ROOT, "json", "companies.json")


def load_companies_json():
    try:
        with open(COMPANIES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def sanitize_msg_id(mid: str) -> str:
    return mid.strip().lstrip("<").rstrip(">")


def find_company_for_email(
    sender_addr: str, from_display: str, subject: str, companies_json: dict
):
    # 1) domain lookup
    domain_map = companies_json.get("domain_to_company", {})
    known = set([s.lower() for s in companies_json.get("known", [])])

    if sender_addr and "@" in sender_addr:
        domain = sender_addr.split("@")[-1].lower()
        mapped = domain_map.get(domain)
        if mapped:
            c = Company.objects.filter(name=mapped).first()
            if c:
                return c, "domain_map"
    # 2) look for known company name in from_display or subject
    combined = " ".join(filter(None, [from_display or "", subject or ""])).lower()
    for name in companies_json.get("known", []):
        if name.lower() in combined:
            c = Company.objects.filter(name=name).first()
            if c:
                return c, "known_in_text"
    # 3) fallback: no match
    return None, None


def extract_body(msg):
    # Return (text, html)
    text = None
    html = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and text is None:
                try:
                    text = part.get_content().strip()
                except Exception:
                    text = part.get_payload(decode=True).decode(errors="ignore").strip()
            elif ctype == "text/html" and html is None:
                try:
                    html = part.get_content().strip()
                except Exception:
                    html = part.get_payload(decode=True).decode(errors="ignore").strip()
    else:
        ctype = msg.get_content_type()
        try:
            payload = msg.get_content()
        except Exception:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                payload = payload.decode(errors="ignore")
        if ctype == "text/plain":
            text = payload.strip()
        elif ctype == "text/html":
            html = payload.strip()
    return text, html


def ingest_eml_bytes(
    raw_bytes: bytes,
    apply: bool = False,
    create_tt: bool = True,
    thread_id_override: str = None,
    auto_confirm: bool = True,
):
    """Parse raw .eml bytes and optionally persist into DB.

    Returns a dict with keys: success (bool), message (str), details (dict)
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    except Exception as e:
        return {"success": False, "message": f"Failed to parse .eml: {e}"}

    # Validate minimal headers
    mid = msg["Message-ID"]
    from_hdr = msg["From"]
    to_hdr = msg["To"]
    date_hdr = msg["Date"]
    subject = msg["Subject"] or ""

    missing = [
        h
        for h, v in [
            ("Message-ID", mid),
            ("From", from_hdr),
            ("To", to_hdr),
            ("Date", date_hdr),
            ("Subject", subject),
        ]
        if not v
    ]
    if missing:
        return {
            "success": False,
            "message": f"Missing required headers: {', '.join(missing)}",
        }

    msg_id = sanitize_msg_id(mid)
    from_name, from_addr = parseaddr(from_hdr)

    # Parse date
    try:
        dt = parsedate_to_datetime(date_hdr)
        if dt.tzinfo is None:
            dt = timezone.make_aware(dt)
    except Exception:
        dt = timezone.now()

    text, html = extract_body(msg)

    companies_json = load_companies_json()
    company_obj, reason = find_company_for_email(
        from_addr, from_name, subject, companies_json
    )

    # Try to assign thread_id by matching existing message subject+company
    thread_id = None
    if thread_id_override:
        thread_id = thread_id_override
    else:
        if company_obj:
            existing = (
                Message.objects.filter(
                    company=company_obj, subject__icontains=subject[:40]
                )
                .order_by("-timestamp")
                .first()
            )
            if existing:
                thread_id = existing.thread_id
        if not thread_id:
            thread_id = msg_id

    details = {
        "msg_id": msg_id,
        "from": f"{from_name} <{from_addr}>",
        "date": dt.isoformat(),
        "subject": subject,
        "company": company_obj.name if company_obj else None,
        "company_reason": reason,
        "thread_id": thread_id,
        "has_text": bool(text),
        "has_html": bool(html),
    }

    if not apply:
        return {"success": True, "message": "Dry-run", "details": details}

    # Persist
    if Message.objects.filter(msg_id=msg_id).exists():
        return {
            "success": False,
            "message": f"Message with msg_id={msg_id} already exists",
        }

    if company_obj is None:
        UnresolvedCompany.objects.create(
            msg_id=msg_id,
            subject=subject or "",
            body=text or (html or ""),
            sender=from_addr or "",
            sender_domain=(
                from_addr.split("@")[-1] if from_addr and "@" in from_addr else ""
            ),
            timestamp=dt,
        )

    msg_rec = Message.objects.create(
        company=company_obj,
        company_source="upload",
        sender=from_addr or "",
        subject=subject or "",
        body=text or (html or ""),
        body_html=html or "",
        timestamp=dt,
        msg_id=msg_id,
        thread_id=thread_id,
        ml_label=None,
        confidence=None,
        reviewed=False,
    )

    details["created_message_id"] = msg_rec.id

    if create_tt and msg_rec.company:
        tt, created = ThreadTracking.objects.get_or_create(
            thread_id=msg_rec.thread_id,
            defaults={
                "company": msg_rec.company,
                "company_source": msg_rec.company_source or "upload",
                "job_title": "",
                "job_id": "",
                "status": msg_rec.ml_label or "application",
                "sent_date": msg_rec.timestamp.date() if msg_rec.timestamp else None,
                "rejection_date": None,
                "interview_date": None,
                "ml_label": msg_rec.ml_label,
                "ml_confidence": msg_rec.confidence,
                "reviewed": False,
            },
        )
        details["threadtracking_id"] = tt.id

    # Run classification using the same pipeline as re-ingest / parser, if available
    try:
        if parse_raw_message and predict_with_fallback and predict_subject_type:
            # Use the already-extracted clean body (text or html) instead of re-parsing
            # to avoid including delivery headers (Return-Path, Received, etc.)
            body_for_classify = text or html or ""

            ml = predict_with_fallback(
                predict_subject_type,
                subject or "",
                body_for_classify or "",
                threshold=0.6,
                sender=from_addr or "",
            )
            if ml and isinstance(ml, dict):
                ml_label = ml.get("label")
                ml_conf = float(ml.get("confidence", 0.0) or 0.0)
                classification_source = ml.get("fallback") or "ml"

                # If classified as noise, clear company assignment
                if ml_label == "noise":
                    msg_rec.company = None
                    msg_rec.company_source = ""

                # Persist to Message
                msg_rec.ml_label = ml_label
                msg_rec.confidence = ml_conf
                msg_rec.classification_source = classification_source
                msg_rec.save()

                details["ml_label"] = ml_label
                details["ml_confidence"] = ml_conf
                details["classification_source"] = classification_source

                # Extract and persist status dates (rejection/interview) using parser helper
                try:
                    if extract_status_dates:
                        status_dates = extract_status_dates(
                            body_for_classify or (text or ""), dt
                        )

                        # Normalize to date objects
                        def _to_date(val):
                            from datetime import datetime, date

                            if val is None:
                                return None
                            if isinstance(val, date):
                                return val
                            if isinstance(val, datetime):
                                return val.date()
                            if isinstance(val, str) and val.strip():
                                for fmt in (
                                    "%Y-%m-%d %H:%M:%S",
                                    "%Y-%m-%d",
                                    "%m/%d/%Y",
                                ):
                                    try:
                                        return datetime.strptime(
                                            val.strip(), fmt
                                        ).date()
                                    except Exception:
                                        continue
                            return None

                        rej_date = (
                            _to_date(status_dates.get("rejection_date"))
                            if status_dates
                            else None
                        )
                        int_date = (
                            _to_date(status_dates.get("interview_date"))
                            if status_dates
                            else None
                        )
                    else:
                        rej_date = None
                        int_date = None
                except Exception:
                    rej_date = None
                    int_date = None

                # Fallback behavior: when ML indicates rejection/interview but no explicit
                # date was parsed, derive a conservative milestone from the message timestamp.
                try:
                    if ml_label:
                        ml_lower = str(ml_label).lower()
                        # Rejection variants
                        if not rej_date and ml_lower in ("rejected", "rejection"):
                            rej_date = dt.date()
                        # Interview variants (only if confidence sufficient)
                        if not int_date and "interview" in ml_lower:
                            try:
                                conf_val = float(ml_conf)
                            except Exception:
                                conf_val = 0.0
                            if conf_val >= 0.7:
                                int_date = dt.date()
                except Exception:
                    # Non-fatal: if anything goes wrong, leave dates as None
                    pass

                # Propagate to ThreadTracking if created or existing
                if create_tt and msg_rec.company:
                    try:
                        tt.ml_label = ml_label
                        tt.ml_confidence = ml_conf
                        # Update status to label when available (keep existing otherwise)
                        if ml_label:
                            tt.status = ml_label
                        # Update milestone dates if present
                        if rej_date:
                            tt.rejection_date = rej_date
                        if int_date:
                            tt.interview_date = int_date
                        tt.save()
                        details["threadtracking_updated"] = tt.id
                        if rej_date:
                            details["threadtracking_rejection_date"] = (
                                rej_date.isoformat()
                            )
                        if int_date:
                            details["threadtracking_interview_date"] = (
                                int_date.isoformat()
                            )
                    except Exception:
                        pass
    except Exception:
        # Non-fatal: classification missing or failed; keep original behavior
        pass

    return {"success": True, "message": "Created", "details": details}


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a .eml file into Message table"
    )
    parser.add_argument("--file", "-f", required=True, help="Path to .eml file")
    parser.add_argument("--apply", action="store_true", help="Persist changes to DB")
    parser.add_argument(
        "--no-tt",
        action="store_true",
        help="Do NOT create ThreadTracking after ingest (default: create TT)",
    )
    parser.add_argument(
        "--thread-id", help="Override thread_id to use for this message (optional)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    path = args.file
    if not os.path.isfile(path):
        print(f"❌ File not found: {path}")
        sys.exit(1)

    raw = open(path, "rb").read()
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as e:
        print(f"❌ Failed to parse .eml: {e}")
        sys.exit(1)

    # Validate minimal headers
    mid = msg["Message-ID"]
    from_hdr = msg["From"]
    to_hdr = msg["To"]
    date_hdr = msg["Date"]
    subject = msg["Subject"] or ""

    missing = [
        h
        for h, v in [
            ("Message-ID", mid),
            ("From", from_hdr),
            ("To", to_hdr),
            ("Date", date_hdr),
            ("Subject", subject),
        ]
        if not v
    ]
    if missing:
        print(f"❌ Missing required headers: {', '.join(missing)}. Aborting.")
        sys.exit(1)

    msg_id = sanitize_msg_id(mid)
    from_name, from_addr = parseaddr(from_hdr)

    # Parse date
    try:
        dt = parsedate_to_datetime(date_hdr)
        if dt.tzinfo is None:
            dt = timezone.make_aware(dt)
    except Exception:
        dt = timezone.now()

    text, html = extract_body(msg)

    companies_json = load_companies_json()
    company_obj, reason = find_company_for_email(
        from_addr, from_name, subject, companies_json
    )

    # Try to assign thread_id by matching existing message subject+company
    thread_id = None
    if company_obj:
        existing = (
            Message.objects.filter(company=company_obj, subject__icontains=subject[:40])
            .order_by("-timestamp")
            .first()
        )
        if existing:
            thread_id = existing.thread_id
    if not thread_id:
        thread_id = msg_id

    print("\n📥 Ingest preview:")
    print(f"  File: {path}")
    print(f"  Message-ID: {msg_id}")
    print(f"  From: {from_name} <{from_addr}>")
    print(f"  Date: {dt}")
    print(f"  Subject: {subject}")
    print(
        f"  Candidate Company: {company_obj.name if company_obj else 'None'} (reason={reason})"
    )
    print(f"  Thread ID to use: {thread_id}")
    print(
        f"  Text body present: {'yes' if text else 'no'} | HTML present: {'yes' if html else 'no'}"
    )

    if not args.apply:
        print(
            "\n🔍 Dry-run (no changes). Use --apply to persist this message into the DB."
        )
        return

    if not args.yes:
        resp = input("Apply changes to DB? (y/N): ")
        if resp.lower() != "y":
            print("❌ Aborted by user")
            return

    # Check duplicate msg_id
    if Message.objects.filter(msg_id=msg_id).exists():
        print(
            f"❌ Message with msg_id={msg_id} already exists in DB. Aborting to avoid duplicate."
        )
        return

    # If company_obj is None, create UnresolvedCompany entry
    if company_obj is None:
        UnresolvedCompany.objects.create(
            msg_id=msg_id,
            subject=subject or "",
            body=text or (html or ""),
            sender=from_addr or "",
            sender_domain=(
                from_addr.split("@")[-1] if from_addr and "@" in from_addr else ""
            ),
            timestamp=dt,
        )
        print(f"ℹ️ Created UnresolvedCompany entry for msg_id={msg_id}")

    # Allow thread-id override from CLI
    if args.thread_id:
        thread_id = args.thread_id

    # Create Message
    msg_rec = Message.objects.create(
        company=company_obj,
        company_source="upload",
        sender=from_addr or "",
        subject=subject or "",
        body=text or (html or ""),
        body_html=html or "",
        timestamp=dt,
        msg_id=msg_id,
        thread_id=thread_id,
        ml_label=None,
        confidence=None,
        reviewed=False,
    )

    print(
        f"✅ Message created id={msg_rec.id} msg_id={msg_rec.msg_id} thread_id={msg_rec.thread_id}"
    )

    # By default create ThreadTracking for uploaded messages when applying, unless --no-tt
    create_tt_flag = not args.no_tt
    if create_tt_flag:
        if not msg_rec.company:
            print(
                f"⚠️ Skipping ThreadTracking creation because company is unresolved for msg_id={msg_id}"
            )
        else:
            tt, created = ThreadTracking.objects.get_or_create(
                thread_id=msg_rec.thread_id,
                defaults={
                    "company": msg_rec.company,
                    "company_source": msg_rec.company_source or "upload",
                    "job_title": "",
                    "job_id": "",
                    "status": msg_rec.ml_label or "application",
                    "sent_date": (
                        msg_rec.timestamp.date() if msg_rec.timestamp else None
                    ),
                    "rejection_date": None,
                    "interview_date": None,
                    "ml_label": msg_rec.ml_label,
                    "ml_confidence": msg_rec.confidence,
                    "reviewed": False,
                },
            )
            if created:
                print(f"✅ ThreadTracking created id={tt.id} for thread {tt.thread_id}")
            else:
                print(f"ℹ️ ThreadTracking already exists id={tt.id}")


if __name__ == "__main__":
    main()
