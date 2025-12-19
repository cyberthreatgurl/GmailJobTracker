import json

import re
from collections import Counter, defaultdict
from pathlib import Path

from django.utils.timezone import now

from tracker.models import Message


def load_patterns_with_legacy_rejection(patterns_path: Path) -> dict:
    """Load patterns.json and re-introduce the legacy 'unfortunately' token
    in the rejection patterns for a before/after audit.
    """
    with open(patterns_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ml = data.setdefault("message_labels", {})
    rej = ml.setdefault("rejection", [])
    # Ensure legacy generic token is present for the simulated 'before' state
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


def legacy_rule_label(subject: str, body: str, compiled: dict) -> str | None:
    """Simulate the legacy rule priority used BEFORE the recent change.

    Old priority:
      offer -> rejected -> interview_invite -> job_application -> referral -> head_hunter -> noise
    """
    text = f"{subject or ''} {body or ''}"
    for label in (
        "offer",
        "rejected",
        "interview_invite",
        "job_application",
        "referral",
        "head_hunter",
        "noise",
    ):
        for rx in compiled.get(label, []):
            if rx.search(text):
                return label
    return None


def run(limit: int | None = None):
    patterns_path = Path("json/patterns.json")
    legacy_patterns = load_patterns_with_legacy_rejection(patterns_path)
    compiled_legacy = compile_patterns(legacy_patterns)

    qs = Message.objects.all().order_by("-timestamp")
    if limit:
        qs = qs[:limit]

    deltas = []
    counts_by_subject = Counter()
    examples_by_subject = defaultdict(list)

    for m in qs.iterator():
        before = legacy_rule_label(m.subject or "", m.body or "", compiled_legacy)
        after = m.ml_label or None
        if before == "rejected" and after != "rejected":
            subj_key = (m.subject or "").strip()[:120]
            counts_by_subject[subj_key] += 1
            if len(examples_by_subject[subj_key]) < 3:
                examples_by_subject[subj_key].append(
                    {
                        "id": m.id,
                        "ts": m.timestamp.isoformat() if m.timestamp else None,
                        "after": after,
                        "sender": m.sender,
                        "company": getattr(m.company, "name", None),
                    }
                )
            deltas.append((m.id, before, after, subj_key))

    print("\n=== False-positive rejections (legacy rules) → current label deltas ===")
    total = sum(counts_by_subject.values())
    print(f"Total deltas: {total}")

    for subj, cnt in counts_by_subject.most_common(30):
        print(f"\n[{cnt}] {subj}")
        for ex in examples_by_subject[subj]:
            print(
                f"   • id={ex['id']} ts={ex['ts']} → after={ex['after']} sender={ex['sender']} company={ex['company']}"
            )


def audit_unfortunately(limit: int | None = None):
    patterns_path = Path("json/patterns.json")
    legacy_patterns = load_patterns_with_legacy_rejection(patterns_path)
    compiled_legacy = compile_patterns(legacy_patterns)

    qs = Message.objects.filter(
        (Message._meta.get_field("subject").get_internal_type() and True)
    ).order_by("-timestamp")
    # Above silly filter is a placeholder; we'll just scan all and test substring
    if limit:
        qs = qs[:limit]

    total = 0
    legacy_rej = 0
    now_rej = 0
    examples = []
    for m in qs.iterator():
        text = f"{m.subject or ''} {m.body or ''}".lower()
        if "unfortunately" not in text:
            continue
        total += 1
        before = legacy_rule_label(m.subject or "", m.body or "", compiled_legacy)
        after = m.ml_label or None
        if before == "rejected":
            legacy_rej += 1
        if after == "rejected":
            now_rej += 1
        if len(examples) < 10:
            examples.append(
                {
                    "id": m.id,
                    "subj": (m.subject or "")[:120],
                    "before": before,
                    "after": after,
                    "ts": m.timestamp.isoformat() if m.timestamp else None,
                }
            )

    print("\n=== 'Unfortunately' audit ===")
    print(f"Messages containing 'unfortunately': {total}")
    print(f"Legacy rules would label rejected: {legacy_rej}")
    print(f"Current DB labeled rejected:      {now_rej}")
    print("\nExamples:")
    for ex in examples:
        print(
            f"  id={ex['id']} before={ex['before']} after={ex['after']} ts={ex['ts']} subj={ex['subj']}"
        )


if __name__ == "__main__":
    run()
    audit_unfortunately()
