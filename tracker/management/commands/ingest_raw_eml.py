import json
import os
import hashlib
from django.core.management.base import BaseCommand
from parser import parse_raw_message, parse_subject, predict_subject_type

class Command(BaseCommand):
    help = "Dry-run classification of a raw .eml file (no DB write)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to .eml file")
        parser.add_argument("--show-body", action="store_true", help="Print first 800 chars of body")
        parser.add_argument("--json", action="store_true", help="Output full JSON result")

    def handle(self, *args, **opts):
        path = opts["file"]
        if not os.path.exists(path):
            self.stderr.write(f"File not found: {path}")
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        meta = parse_raw_message(raw)
        subject = meta.get("subject", "")
        body = meta.get("body", "")
        sender = meta.get("sender", "")
        sender_domain = meta.get("sender_domain")
        parsed = parse_subject(subject, body, sender=sender, sender_domain=sender_domain) or {}
        company = parsed.get("company")
        ml = predict_subject_type(subject, body, sender=sender)
        ml_label = ml.get("label") if isinstance(ml, dict) else None
        ml_conf = float(ml.get("confidence", ml.get("proba", 0.0))) if isinstance(ml, dict) else 0.0
        header_hints = meta.get("header_hints", {})
        synthetic_id = hashlib.md5((subject + sender + str(meta.get("date"))).encode()).hexdigest()[:16]
        result = {
            "synthetic_msg_id": synthetic_id,
            "subject": subject,
            "sender": sender,
            "sender_domain": sender_domain,
            "company": company,
            "parsed": parsed,
            "ml_label": ml_label,
            "ml_confidence": ml_conf,
            "header_hints": header_hints,
            "body_preview": body[:800] + ("..." if len(body) > 800 else ""),
        }
        if opts["json"]:
            self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
            return
        self.stdout.write(f"Subject: {subject}\nSender: {sender}\nCompany: {company or '(none)'}\nLabel: {ml_label} ({ml_conf:.2f})")
        if header_hints:
            self.stdout.write(f"Header hints: {header_hints}")
        # argparse converts '--show-body' to 'show_body'
        if opts.get("show_body"):
            self.stdout.write("\nBody Preview:\n" + result["body_preview"])