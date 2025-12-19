"""Check actual email body content."""

import sys
import email
from pathlib import Path

eml_path = Path(
    r"d:\Users\kaver\Downloads\Deep Dive_ China's Global Strategy and Power Balance.eml"
)
if eml_path.exists():
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f)

    subject = msg.get("Subject", "")
    print(f"Subject: {subject}")
    print()

    # Get body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")
                    print(f"Content-Type: {part.get_content_type()}")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="ignore")

    print(f"Body (first 2000 chars):")
    print(body[:2000])
    print()
    print("=" * 80)
    print(f'Body contains "newsletter": {"newsletter" in body.lower()}')
    print(f'Body contains "digest": {"digest" in body.lower()}')
    print(f'Body contains "recommendation": {"recommendation" in body.lower()}')
else:
    print(f"File not found: {eml_path}")
