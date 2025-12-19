#!/usr/bin/env python3
"""Generate a concise mismatch report from review_reports/batch_eml_parse_report.json

Prints rows where rule_label differs from ml_label and shows flagged examples.
"""
import json
from pathlib import Path

REPORT = Path("review_reports") / "batch_eml_parse_report.json"
if not REPORT.exists():
    print("Report not found:", REPORT)
    raise SystemExit(1)

with REPORT.open("r", encoding="utf-8") as fh:
    data = json.load(fh)

rows = data.get("rows", [])
mis = []
for r in rows:
    ml = str(r.get("ml_label"))
    rl = str(r.get("rule_label"))
    # treat 'None' (string) and None equivalently
    if rl.lower() != "none" and rl != ml:
        mis.append(r)

print(f"Total rows: {len(rows)}; mismatches: {len(mis)}\n")
for r in mis:
    hh = r.get("header_hints", {}) or {}
    print(
        f"- {r['file']} | ml={r.get('ml_label')} | rule={r.get('rule_label')} | final={r.get('final_label')} | reply_to={hh.get('reply_to')}"
    )

# Print flagged examples (the ones you mentioned)
flags = [
    "tests\\email\\Update on Leidos Position Full Spectrum Cyber AI Researcher (1).eml",
    "tests\\email\\Thank You from Simventions, Inc.eml",
]
print("\nFLAGGED EXAMPLES:")
for r in rows:
    if r["file"] in flags:
        print(json.dumps(r, indent=2, ensure_ascii=False))
