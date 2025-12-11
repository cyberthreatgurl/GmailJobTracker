"""Email body extraction and parsing utilities.

This module contains the EmailBodyParser class which handles extraction of body
text from various email formats (Gmail API payloads, raw EML messages), decoding
of MIME parts, and conversion of HTML to plain text.
"""

import base64
import quopri
import re
from email import message_from_string
from email.utils import parseaddr
from email.header import decode_header as eml_decode_header
from bs4 import BeautifulSoup
from typing import Optional, Dict


DEBUG = False  # Set to True for verbose body parsing debugging


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

        Walks nested multipart sections; prefers HTML and returns full HTML string.
        
        Args:
            parts: List of Gmail API message parts
            
        Returns:
            HTML body string, "Empty Body" if empty, or "" if not found
        """
        for part in parts:
            mime_type = part.get("mimeType")
            body_data = part.get("body", {}).get("data")
            
            if mime_type == "text/html" and body_data:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                if not decoded:
                    decoded = "Empty Body"
                    if DEBUG:
                        print("Decoded Body/HTML part is empty.")
                return decoded  # preserve full HTML
            elif "parts" in part:
                result = EmailBodyParser.extract_from_gmail_parts(part["parts"])
                if result:
                    return result
                else:
                    return "Empty Body"
        
        return ""

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
                        decoded_chunks.append(text.decode(enc or "utf-8", errors="ignore"))
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
    def parse_raw_eml(raw_text: str, now_fn=None) -> Dict:
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
        from django.utils import timezone
        from datetime import datetime
        from email.utils import parsedate_to_datetime
        
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
            eml = message_from_string(raw_text)
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
        date_raw = eml.get("Date", "")
        
        try:
            date_obj = parsedate_to_datetime(date_raw)
            if timezone.is_naive(date_obj):
                date_obj = timezone.make_aware(date_obj)
        except Exception:
            date_obj = now_fn()
        
        date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")

        # Extract sender domain
        parsed = parseaddr(sender)
        email_addr = parsed[1] if len(parsed) == 2 else ""
        match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
        sender_domain = match.group(1).lower() if match else ""

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
                    decoded = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
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
                    body_text = payload.decode(eml.get_content_charset() or "utf-8", errors="ignore")
            except Exception:
                body_text = raw_text

        if body_html and not body_text:
            # Provide plain text fallback from HTML
            body_text = EmailBodyParser.html_to_text(body_html)

        # Header hints similar to Gmail path (limited set for EML)
        header_hints = {
            "is_newsletter": any(h in eml for h in ["List-Id", "List-Unsubscribe", "X-Newsletter"]),
            "is_bulk": EmailBodyParser.decode_header_value(eml.get("Precedence", "")).lower() == "bulk",
            "is_noreply": "noreply" in sender.lower() or "no-reply" in sender.lower(),
            "reply_to": EmailBodyParser.decode_header_value(eml.get("Reply-To", "")) or None,
            "organization": EmailBodyParser.decode_header_value(eml.get("Organization", "")) or None,
            "auto_submitted": EmailBodyParser.decode_header_value(eml.get("Auto-Submitted", "")).lower() not in ("", "no"),
        }

        # Combine headers for classification like Gmail version
        header_text = []
        for h_name, h_val in eml.items():
            if h_name.lower() in {"list-id", "list-unsubscribe", "precedence", "reply-to", "organization"}:
                header_text.append(f"{h_name}: {h_val}")
        
        body_for_classification = ("\n".join(header_text) + "\n\n" + (body_text or "")).strip()

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
            "header_hints": header_hints,
        }
