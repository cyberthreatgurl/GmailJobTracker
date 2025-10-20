from django.core.management.base import BaseCommand
import os
import json
from parser import (
    extract_metadata,
    parse_subject,
    resolve_company,
    predict_subject_type,
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
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        # Try to parse as JSON first
        try:
            msg = json.loads(raw)
        except Exception:
            msg = raw  # fallback: treat as raw string (EML)
        # Extract metadata
        meta = extract_metadata(msg)
        subject = meta.get("subject", "")
        body = meta.get("body", "")
        sender = meta.get("sender", "")
        thread_id = meta.get("thread_id", "")
        # Parse subject and company
        parsed = parse_subject(subject)
        company = resolve_company(sender, body, subject)
        label, confidence = predict_subject_type(subject, body)
        result = {
            "subject": subject,
            "body": body,
            "sender": sender,
            "thread_id": thread_id,
            "parsed_subject": parsed,
            "company": company,
            "ml_label": label,
            "ml_confidence": confidence,
        }
        if options["verbose"]:
            self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(
                f"Subject: {subject}\nCompany: {company}\nLabel: {label} ({confidence:.2f})"
            )
