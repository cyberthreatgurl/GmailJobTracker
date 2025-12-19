import json
import os
from django.core.management.base import BaseCommand
from parser import (
    parse_subject,
    predict_subject_type,
    parse_raw_message,
)


class Command(BaseCommand):
    help = (
        "Parse a raw Gmail message source and print the extracted fields (no DB write)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the raw Gmail message source (JSON or .eml)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print all extracted fields verbosely.",
        )

    def handle(self, *args, **options):
        file_path = options["file"]
        if not os.path.exists(file_path):
            self.stderr.write(f"File not found: {file_path}")
            return
        # Load raw message
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()

        # Attempt JSON parse (Gmail API full response). If it fails, treat as raw EML.
        msg_obj = None
        meta = None
        try:
            msg_obj = json.loads(raw)
            # If it looks like a Gmail API message (has payload & id), build minimal wrapper
            if isinstance(msg_obj, dict) and "payload" in msg_obj and "id" in msg_obj:
                # We need a Gmail service for extract_metadata; not available here, so fallback to raw parse
                meta = parse_raw_message(raw)
            else:
                # Generic JSON isn't a Gmail API message; treat as raw
                meta = parse_raw_message(raw)
        except json.JSONDecodeError as e:
            # Provide detailed context on failure
            snippet = raw[:400].replace("\n", " ")
            self.stderr.write(
                f"JSON decode failed at pos={e.pos}: {e.msg}. Falling back to raw EML parsing. Snippet: {snippet}"
            )
            meta = parse_raw_message(raw)
        except Exception as e:
            self.stderr.write(
                f"Unexpected parse error ({e}); treating input as raw EML"
            )
            meta = parse_raw_message(raw)

        if not meta:
            self.stderr.write("Failed to derive metadata from message.")
            return

        subject = meta.get("subject", "")
        body = meta.get("body", "")
        sender = meta.get("sender", "")
        thread_id = meta.get("thread_id", "")
        # Core classification pipeline
        parsed = (
            parse_subject(
                subject, body, sender=sender, sender_domain=meta.get("sender_domain")
            )
            or {}
        )
        company = parsed.get("company")  # company resolution handled in parse_subject
        ml_result = predict_subject_type(subject, body, sender=sender)
        label = ml_result.get("label") if isinstance(ml_result, dict) else None
        confidence = (
            float(ml_result.get("confidence", ml_result.get("proba", 0.0)))
            if isinstance(ml_result, dict)
            else 0.0
        )
        result = {
            "subject": subject,
            "body": body,
            "sender": sender,
            "thread_id": thread_id,
            "parsed_subject": parsed,
            "company": company,
            "ml_label": label,
            "ml_confidence": confidence,
            "header_hints": meta.get("header_hints", {}),
        }
        if options["verbose"]:
            self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(
                f"Subject: {subject}\nCompany: {company or '(none)'}\nLabel: {label} ({confidence:.2f})"
            )
