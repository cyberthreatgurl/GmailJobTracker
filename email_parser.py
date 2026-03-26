"""Email body parsing and metadata extraction classes.

Extracted from parser.py for maintainability. Contains:
- EmailBodyParser: MIME decoding, Gmail API payload extraction, EML parsing, HTML-to-text
- MetadataExtractor: Status dates, iCalendar organizer, job ID extraction

These classes are used by parser.py and are instantiated at module level.
"""

import base64
import logging
import re
import quopri
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from email import message_from_string as eml_from_string
from email.header import decode_header as eml_decode_header

from bs4 import BeautifulSoup
from django.utils import timezone

logger = logging.getLogger("parser")


class EmailBodyParser:
    """Parses and extracts body text from email messages.

    This class handles:
    - MIME part decoding (base64, quoted-printable, 7bit)
    - Gmail API payload body extraction (recursive multipart handling)
    - Raw EML message parsing
    - HTML to plain text conversion
    - Header extraction for classification
    """

    @staticmethod
    def decode_mime_part(data: str, encoding: str) -> str:
        """Decode a MIME part body string using the provided encoding.

        Supports base64, quoted-printable, and 7bit. Returns a decoded UTF-8 string.

        Args:
            data: Encoded MIME part data
            encoding: Encoding type (base64, quoted-printable, 7bit)

        Returns:
            Decoded UTF-8 string
        """
        if encoding == "base64":
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        elif encoding == "quoted-printable":
            return quopri.decodestring(data).decode("utf-8", errors="ignore")
        elif encoding == "7bit":
            return data  # usually already decoded
        else:
            return data

    @staticmethod
    def extract_from_gmail_parts(parts: list) -> str:
        """Extract the first HTML part's body from a Gmail message payload tree.

        Walks nested multipart sections; prefers HTML and falls back to plain text.

        Args:
            parts: List of Gmail API message parts

        Returns:
            HTML body string, plain-text body string, or "" if not found
        """
        plain_fallback = ""

        for part in parts:
            mime_type = part.get("mimeType")
            body_data = part.get("body", {}).get("data")

            if mime_type == "text/html" and body_data:
                decoded = base64.urlsafe_b64decode(body_data).decode(
                    "utf-8", errors="ignore"
                )
                if decoded:
                    return decoded  # preserve full HTML
                logger.debug("Decoded Body/HTML part is empty.")
            elif mime_type == "text/plain" and body_data and not plain_fallback:
                plain_fallback = base64.urlsafe_b64decode(body_data).decode(
                    "utf-8", errors="ignore"
                )

            nested_parts = part.get("parts") or []
            if nested_parts:
                result = EmailBodyParser.extract_from_gmail_parts(nested_parts)
                if result:
                    return result

        return plain_fallback or ""

    @staticmethod
    def decode_header_value(raw_val: str) -> str:
        """Decode RFC 2047 encoded header values to unicode.

        Falls back gracefully on decode errors, always returns a str.

        Args:
            raw_val: Raw header value (may be RFC 2047 encoded)

        Returns:
            Decoded unicode string
        """
        if not raw_val:
            return ""

        try:
            parts = eml_decode_header(raw_val)
            decoded_chunks = []
            for text, enc in parts:
                if isinstance(text, bytes):
                    try:
                        decoded_chunks.append(
                            text.decode(enc or "utf-8", errors="ignore")
                        )
                    except Exception:
                        decoded_chunks.append(text.decode("utf-8", errors="ignore"))
                else:
                    decoded_chunks.append(text)
            return "".join(decoded_chunks)
        except Exception:
            return raw_val

    @staticmethod
    def html_to_text(html: str) -> str:
        """Convert HTML to plain text using BeautifulSoup.

        Args:
            html: HTML content

        Returns:
            Plain text with HTML tags removed
        """
        if not html:
            return ""

        try:
            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style tags
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            return html

    @staticmethod
    def extract_forwarded_message_date(body_text: str, body_html: str = ""):
        """Extract the original sent date from a forwarded-message header block."""
        headers = EmailBodyParser.extract_forwarded_message_headers(body_text, body_html)
        return headers.get("date")

    @staticmethod
    def extract_forwarded_message_headers(body_text: str, body_html: str = "") -> dict:
        """Extract original From/Date/Subject/To from a forwarded-message block."""
        candidates = []
        if body_text:
            candidates.append(body_text)
        if body_html:
            candidates.append(EmailBodyParser.html_to_text(body_html))

        for candidate in candidates:
            headers = EmailBodyParser._parse_forwarded_headers_from_text(candidate)
            if headers:
                return headers
        return {}

    @staticmethod
    def _parse_forwarded_headers_from_text(text: str) -> dict:
        """Parse a forwarded Gmail-style header block from plain text."""
        if not text:
            return {}

        normalized = text.replace("\u202f", " ").replace("\xa0", " ")
        marker = re.search(r"forwarded message", normalized, flags=re.IGNORECASE)
        if not marker:
            return {}

        header_block = normalized[marker.start(): marker.start() + 1500]

        extracted = {}
        for field in ("from", "date", "subject", "to"):
            field_match = re.search(
                rf"\b{field}:\s*(.+?)(?=\bfrom:|\bdate:|\bsubject:|\bto:|$)",
                header_block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if field_match:
                extracted[field] = re.sub(r"\s+", " ", field_match.group(1)).strip(" :-")

        date_text = extracted.get("date", "")
        if not date_text:
            return extracted
        normalized_date_text = date_text.replace(" at ", " ")

        # Gmail forwarded headers often use "Thu, Mar 6, 2025 at 8:41 PM".
        # parsedate_to_datetime can drop the meridiem on that shape, so prefer
        # explicit strptime formats when AM/PM is present.
        if re.search(r"\b(?:AM|PM)\b", normalized_date_text, re.IGNORECASE):
            for fmt in (
                "%a, %b %d, %Y %I:%M %p",
                "%a, %b %d, %Y, %I:%M %p",
                "%b %d, %Y %I:%M %p",
                "%b %d, %Y, %I:%M %p",
            ):
                try:
                    date_obj = datetime.strptime(normalized_date_text, fmt)
                    if timezone.is_naive(date_obj):
                        date_obj = timezone.make_aware(date_obj)
                    extracted["date"] = date_obj
                    return extracted
                except Exception:
                    continue

        for candidate in (
            date_text,
            normalized_date_text,
        ):
            try:
                date_obj = parsedate_to_datetime(candidate)
                if timezone.is_naive(date_obj):
                    date_obj = timezone.make_aware(date_obj)
                extracted["date"] = date_obj
                return extracted
            except Exception:
                pass

        for fmt in (
            "%a, %b %d, %Y %H:%M",
            "%a, %b %d, %Y, %H:%M",
            "%b %d, %Y %H:%M",
            "%b %d, %Y, %H:%M",
        ):
            try:
                date_obj = datetime.strptime(normalized_date_text, fmt)
                if timezone.is_naive(date_obj):
                    date_obj = timezone.make_aware(date_obj)
                extracted["date"] = date_obj
                return extracted
            except Exception:
                continue

        return extracted

    @staticmethod
    def parse_raw_eml(raw_text: str, now_fn=None):
        """Parse a raw EML (RFC 822) message string and return metadata.

        This allows debugging/ingesting messages pasted into the UI or loaded from disk
        without requiring a live Gmail API service call.

        Args:
            raw_text: Raw EML message text
            now_fn: Function to get current time (for testing)

        Returns:
            Dictionary with keys: subject, body, body_html, timestamp, date(str),
            sender, sender_domain, thread_id(None), labels(""), last_updated, header_hints
        """
        if now_fn is None:
            now_fn = timezone.now

        if not raw_text:
            return {
                "subject": "",
                "body": "",
                "body_html": "",
                "timestamp": now_fn(),
                "date": now_fn().strftime("%Y-%m-%d %H:%M:%S"),
                "sender": "",
                "sender_domain": "",
                "thread_id": None,
                "labels": "",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "header_hints": {},
            }

        try:
            eml = eml_from_string(raw_text)
        except Exception:
            # Return minimal structure if parsing fails
            return {
                "subject": "(parse error)",
                "body": raw_text,
                "body_html": "",
                "timestamp": now_fn(),
                "date": now_fn().strftime("%Y-%m-%d %H:%M:%S"),
                "sender": "",
                "sender_domain": "",
                "thread_id": None,
                "labels": "",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "header_hints": {},
            }

        subject = EmailBodyParser.decode_header_value(eml.get("Subject", ""))
        sender = EmailBodyParser.decode_header_value(eml.get("From", ""))
        to_header = EmailBodyParser.decode_header_value(eml.get("To", ""))
        date_raw = eml.get("Date", "")

        try:
            date_obj = parsedate_to_datetime(date_raw)
            if timezone.is_naive(date_obj):
                date_obj = timezone.make_aware(date_obj)
        except Exception:
            date_obj = now_fn()

        # Walk parts for body (prefer HTML) else text/plain
        body_html = ""
        body_text = ""

        if eml.is_multipart():
            for part in eml.walk():
                ctype = part.get_content_type()
                disp = (part.get("Content-Disposition") or "").lower()

                if "attachment" in disp:
                    continue  # skip attachments

                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    decoded = payload.decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
                except Exception:
                    continue

                if ctype == "text/html" and not body_html:
                    body_html = decoded
                elif ctype == "text/plain" and not body_text:
                    body_text = decoded
        else:
            try:
                payload = eml.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(
                        eml.get_content_charset() or "utf-8", errors="ignore"
                    )
            except Exception:
                body_text = raw_text

        if body_html and not body_text:
            # Provide plain text fallback from HTML
            body_text = EmailBodyParser.html_to_text(body_html)

        forwarded_headers = EmailBodyParser.extract_forwarded_message_headers(
            body_text,
            body_html,
        )
        if forwarded_headers.get("subject"):
            subject = forwarded_headers["subject"]
        if forwarded_headers.get("from"):
            sender = forwarded_headers["from"]
        if forwarded_headers.get("to"):
            to_header = forwarded_headers["to"]
        if forwarded_headers.get("date") is not None:
            date_obj = forwarded_headers["date"]

        # Extract sender domain
        parsed = parseaddr(sender)
        email_addr = parsed[1] if len(parsed) == 2 else ""
        match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
        sender_domain = match.group(1).lower() if match else ""

        date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")

        # Header hints similar to Gmail path (limited set for EML)
        header_hints = {
            "is_newsletter": any(h in eml for h in ["List-Id", "X-Newsletter"]),
            "is_bulk": EmailBodyParser.decode_header_value(
                eml.get("Precedence", "")
            ).lower()
            == "bulk",
            "is_noreply": "noreply" in sender.lower() or "no-reply" in sender.lower(),
            "reply_to": EmailBodyParser.decode_header_value(eml.get("Reply-To", ""))
            or None,
            "organization": EmailBodyParser.decode_header_value(
                eml.get("Organization", "")
            )
            or None,
            "auto_submitted": EmailBodyParser.decode_header_value(
                eml.get("Auto-Submitted", "")
            ).lower()
            not in ("", "no"),
        }

        # Combine headers for classification like Gmail version
        header_text = []
        for h_name, h_val in eml.items():
            if h_name.lower() in {
                "list-id",
                "list-unsubscribe",
                "precedence",
                "reply-to",
                "organization",
            }:
                header_text.append(f"{h_name}: {h_val}")

        body_for_classification = (
            "\n".join(header_text) + "\n\n" + (body_text or "")
        ).strip()

        return {
            "thread_id": None,
            "subject": subject,
            "body": body_for_classification,
            "body_html": body_html,
            "date": date_str,
            "timestamp": date_obj,
            "labels": "",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sender": sender,
            "sender_domain": sender_domain,
            "to": to_header,
            "header_hints": header_hints,
        }


class MetadataExtractor:
    """Extract dates, job IDs, and other metadata from email messages."""

    def __init__(self, rule_classifier=None):
        """
        Initialize MetadataExtractor.

        Args:
            rule_classifier: RuleClassifier instance for accessing compiled patterns
        """
        self._rule_classifier = rule_classifier

    def extract_status_dates(self, body: str, received_date):
        """
        Extract key status dates from email body.

        For interview invites, sets interview_date to 7 days in the future
        to mark as "upcoming" (user can manually update with actual date).

        Args:
            body: Email body text
            received_date: Date the email was received

        Returns:
            Dictionary with response_date, rejection_date, interview_date, follow_up_dates
        """
        body_lower = body.lower()
        dates = {
            "response_date": None,
            "rejection_date": None,
            "interview_date": None,
            "follow_up_dates": [],
        }

        if not self._rule_classifier:
            return dates

        # Use compiled patterns from RuleClassifier instance
        interview_patterns = self._rule_classifier._msg_label_patterns.get(
            "interview_invite", []
        )
        rejection_patterns = self._rule_classifier._msg_label_patterns.get(
            "rejection", []
        )
        response_patterns = self._rule_classifier._msg_label_patterns.get(
            "response", []
        )
        followup_patterns = self._rule_classifier._msg_label_patterns.get(
            "follow_up", []
        )

        if any(re.search(p, body_lower) for p in response_patterns):
            dates["response_date"] = received_date
        if any(re.search(p, body_lower) for p in rejection_patterns):
            dates["rejection_date"] = received_date
        # NOTE: interview_date is NOT auto-set from pattern matching.
        # It should only be set when:
        #   1. User manually enters the date via UI, OR
        #   2. Email contains explicit date (future enhancement: parse dates from body)
        # The previous "+7 days" heuristic created phantom interview entries.
        if any(re.search(p, body_lower) for p in followup_patterns):
            dates["follow_up_dates"] = received_date
        return dates

    @staticmethod
    def extract_organizer_from_icalendar(body: str):
        """
        Extract organizer email from iCalendar data in message body.

        Teams/Zoom meeting invites often contain BASE64 encoded iCalendar data
        with ORGANIZER field containing the sender's email address.

        Args:
            body: Email body text (may contain BASE64 encoded iCalendar data)

        Returns:
            Tuple of (organizer_email, organizer_domain) or (None, None)
        """
        if not body:
            return None, None

        # Look for BASE64 encoded iCalendar data
        # Pattern: continuous BASE64 string (common in calendar invites)
        base64_pattern = r"(?:[A-Za-z0-9+/]{60,}\n?)+"
        matches = re.findall(base64_pattern, body)

        for match in matches:
            try:
                # Remove newlines and decode
                base64_data = match.replace("\n", "").replace("\r", "")
                decoded = base64.b64decode(base64_data).decode("utf-8", errors="ignore")

                # Check if this is iCalendar data
                if "BEGIN:VCALENDAR" in decoded or "ORGANIZER" in decoded:
                    # Extract ORGANIZER email
                    # Format: ORGANIZER;CN=Name:mailto:email@domain.com
                    organizer_match = re.search(
                        r"ORGANIZER[^:]*:mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                        decoded,
                        re.IGNORECASE,
                    )
                    if organizer_match:
                        email = organizer_match.group(1).lower()
                        domain = email.split("@")[-1] if "@" in email else None
                        logger.debug(
                            f"[DEBUG] Extracted organizer from iCalendar: {email} (domain: {domain})"
                        )
                        return email, domain
            except Exception as e:
                logger.debug(f"[DEBUG] Failed to decode/parse iCalendar data: {e}")
                continue

        return None, None

    @staticmethod
    def extract_job_id(subject: str) -> str:
        """
        Extract job ID from subject line.

        Looks for patterns like:
        - Job #12345
        - Position #ABC-123
        - jobId=XYZ789

        Args:
            subject: Email subject line

        Returns:
            Job ID string or empty string if not found
        """
        if not subject:
            return ""

        id_match = re.search(
            r"(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)", subject, re.IGNORECASE
        )
        return id_match.group(1).strip() if id_match else ""


# ======================================================================================
