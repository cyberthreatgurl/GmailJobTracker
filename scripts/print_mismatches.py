#!/usr/bin/env python3
import json
from pathlib import Path

p = Path("review_reports/batch_eml_parse_report.json")
if not p.exists():
    print("Report not found:", p)
    raise SystemExit(1)
j = json.loads(p.read_text(encoding="utf-8"))
rows = j.get("rows", [])
print("mismatches (ml_label != rule_label):")
count = 0
for r in rows:
    ml = r.get("ml_label")
    rl = r.get("rule_label")
    if str(ml) != str(rl):
        print(f"{r['file']}: ml={ml} rl={rl} final={r.get('final_label')}")
        count += 1
print("\nSummary:")
print(j.get("summary"))
print("\nTotal mismatches printed:", count)
