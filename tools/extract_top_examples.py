#!/usr/bin/env python3
"""Extract top N examples where reviewed label is 'noise' and ML suggests 'referral' or 'head_hunter'.

Writes `review_reports/top_noise_referral_headhunter_examples.csv` (default N=200).
"""
import csv
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "reviewed_disagreements.csv"
OUT_DIR = ROOT / "review_reports"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "top_noise_referral_headhunter_examples.csv"

N = 200

if not IN.exists():
    print(f"Input file not found: {IN}")
    raise SystemExit(1)

rows = []
with IN.open("r", encoding="utf-8", newline="") as inf:
    r = csv.DictReader(inf)
    for row in r:
        old = (row.get("old_label") or "").strip().lower()
        new = (row.get("new_label") or "").strip().lower()
        if old == "noise" and new in ("referral", "head_hunter"):
            rows.append(row)

# Optionally sort by timestamp (newest first)
rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)

with OUT.open("w", encoding="utf-8", newline="") as outf:
    fieldnames = [
        "message_id",
        "thread_id",
        "timestamp",
        "subject",
        "old_label",
        "old_conf",
        "new_label",
        "new_conf",
        "method",
    ]
    w = csv.DictWriter(outf, fieldnames=fieldnames)
    w.writeheader()
    for row in rows[:N]:
        out = {k: row.get(k, "") for k in fieldnames}
        out["subject"] = (out["subject"] or "").replace("\n", " ")[:300]
        w.writerow(out)

print(f"Wrote {min(N, len(rows))} examples -> {OUT}")
