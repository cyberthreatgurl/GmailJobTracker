"""Email and MIME parsing utilities.

Extracted from parser.py Phase 4 refactoring for better organization and reusability.
These functions delegate to the EmailBodyParser class for actual implementation.
"""

from django.utils import timezone


def decode_mime_part(data: str, encoding: str, email_body_parser) -> str:
    """Decode a MIME part body string using the provided encoding.
    
    Delegates to EmailBodyParser.decode_mime_part()
    
    Args:
        data: Encoded MIME part data
        encoding: Encoding type (base64, quoted-printable, 7bit)
        email_body_parser: EmailBodyParser class with decoding methods
        
    Returns:
        Decoded UTF-8 string
    """
    return email_body_parser.decode_mime_part(data, encoding)


def extract_body_from_gmail_parts(parts: list, email_body_parser) -> str:
    """Extract the first HTML part's body from a Gmail message payload tree.
    
    Delegates to EmailBodyParser.extract_from_gmail_parts()
    
    Args:
        parts: List of Gmail API message parts
        email_body_parser: EmailBodyParser class
        
    Returns:
        HTML body string, "Empty Body" if empty, or "" if not found
    """
    return email_body_parser.extract_from_gmail_parts(parts)


def decode_header_value(raw_val: str, email_body_parser) -> str:
    """Decode RFC 2047 encoded header values to unicode.
    
    Delegates to EmailBodyParser.decode_header_value()
    
    Args:
        raw_val: Raw header value (may be RFC 2047 encoded)
        email_body_parser: EmailBodyParser class
        
    Returns:
        Decoded unicode string
    """
    return email_body_parser.decode_header_value(raw_val)


def parse_raw_eml_message(raw_text: str, email_body_parser, now_fn=None) -> dict:
    """Parse a raw EML (RFC 822) message string and return metadata.
    
    Delegates to EmailBodyParser.parse_raw_eml()
    
    Args:
        raw_text: Raw EML message text
        email_body_parser: EmailBodyParser class
        now_fn: Function to get current time (defaults to timezone.now)
        
    Returns:
        Dictionary with keys: subject, body, body_html, timestamp, date(str),
        sender, sender_domain, thread_id(None), labels(""), last_updated, header_hints
    """
    if now_fn is None:
        now_fn = timezone.now
    return email_body_parser.parse_raw_eml(raw_text, now_fn)
