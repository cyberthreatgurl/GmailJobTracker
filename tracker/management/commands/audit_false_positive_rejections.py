import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand

from tracker.models import Message


def load_patterns_with_legacy_rejection(patterns_path: Path) -> dict:
    with open(patterns_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    ml = data.setdefault("message_labels", {})
    rej = ml.setdefault("rejection", [])
    legacy = "\\bunfortunately\\b"
    if legacy not in rej:
        rej.append(legacy)
    return data


def compile_patterns(patterns: dict) -> dict:
    compiled = {}
    for label, pats in patterns.get("message_labels", {}).items():
        compiled[label] = [
            re.compile(p, re.IGNORECASE) for p in pats if p and p != "None"
        ]
    return compiled


def _html_to_text(html: str) -> str:
    try:
        return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    except Exception:
        return html or ""


def legacy_rule_label(subject: str, body: str, compiled: dict) -> str | None:
    text = f"{subject or ''} {_html_to_text(body)}"
    # Patterns file uses keys like 'rejection' and 'interview',
    # whereas DB uses 'rejected' and 'interview_invite'.
    # We'll check both synonyms in a reasonable priority.
    ordered_keys = [
        "offer",
        "rejection",
        "rejected",
        "interview",
        "interview_invite",
        "application",
        "job_application",
        "referral",
        "head_hunter",
        "noise",
    ]
    seen = set()
    for key in ordered_keys:
        if key in seen:
            continue
        seen.add(key)
        for rx in compiled.get(key, []):
            if rx.search(text):
                return key
    return None


class Command(BaseCommand):
    help = "Audit potential false-positive rejections before/after rule change"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--examples", type=int, default=3)
        parser.add_argument("--top", type=int, default=30)
        parser.add_argument(
            "--term",
            type=str,
            default="unfortunately",
            help="Focus term to inspect (lowercased)",
        )

    def handle(self, *args, **opts):
        limit = opts.get("limit")
        max_examples = opts.get("examples")
        topn = opts.get("top")
        focus_term = (opts.get("term") or "unfortunately").lower()

        patterns_path = Path("json/patterns.json")
        legacy_patterns = load_patterns_with_legacy_rejection(patterns_path)
        compiled_legacy = compile_patterns(legacy_patterns)

        qs = Message.objects.all().order_by("-timestamp")
        if limit:
            qs = qs[:limit]

        counts_by_subject = Counter()
        examples_by_subject = defaultdict(list)
        term_total = 0
        term_legacy_rej = 0
        term_now_rej = 0

        for m in qs.iterator():
            text = f"{m.subject or ''} {_html_to_text(m.body)}".lower()
            before = legacy_rule_label(m.subject or "", m.body or "", compiled_legacy)
            # Normalize labels to DB canonical
            norm = {
                "rejection": "rejected",
                "interview": "interview_invite",
                "application": "job_application",
            }
            before_norm = norm.get(before, before)
            after = m.ml_label or None

            # Aggregate deltas overall
            if before_norm == "rejected" and after != "rejected":
                subj_key = (m.subject or "").strip()[:120]
                counts_by_subject[subj_key] += 1
                if len(examples_by_subject[subj_key]) < max_examples:
                    examples_by_subject[subj_key].append(
                        {
                            "id": m.id,
                            "ts": m.timestamp.isoformat() if m.timestamp else None,
                            "after": after,
                            "sender": m.sender,
                            "company": getattr(m.company, "name", None),
                        }
                    )

            # Focus term audit (e.g., 'unfortunately')
            if focus_term and focus_term in text:
                term_total += 1
                if before_norm == "rejected":
                    term_legacy_rej += 1
                if after == "rejected":
                    term_now_rej += 1

        self.stdout.write(
            "\n=== False-positive rejections (legacy rules) → current label deltas ==="
        )
        total = sum(counts_by_subject.values())
        self.stdout.write(f"Total deltas: {total}")

        for subj, cnt in counts_by_subject.most_common(topn):
            self.stdout.write(f"\n[{cnt}] {subj}")
            for ex in examples_by_subject[subj]:
                self.stdout.write(
                    f"   • id={ex['id']} ts={ex['ts']} → after={ex['after']} sender={ex['sender']} company={ex['company']}"
                )

        self.stdout.write("\n=== Focus term audit ===")
        self.stdout.write(f"Term: '{focus_term}' occurrences: {term_total}")
        self.stdout.write(f"Legacy rules → rejected: {term_legacy_rej}")
        self.stdout.write(f"Current DB → rejected:  {term_now_rej}")
