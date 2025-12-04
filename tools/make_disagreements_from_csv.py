#!/usr/bin/env python3
"""Create reviewed_disagreements.csv from the DB-backed export CSV.

This script reads `reclassify_dryrun_full_trimmed_with_ts.csv` (created by
`export_reclassify_dryrun`) and writes rows where `reviewed` is True and
the stored `old_label` differs from the ML `new_label`.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "reclassify_dryrun_full_trimmed_with_ts.csv"
OUT_DIR = ROOT / "review_reports"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "reviewed_disagreements.csv"

if not IN.exists():
    print(f"Input file not found: {IN}")
    raise SystemExit(1)

total = 0
rows = 0
with IN.open("r", encoding="utf-8", newline="") as inf, OUT.open("w", encoding="utf-8", newline="") as outf:
    r = csv.DictReader(inf)
    fieldnames = r.fieldnames or []
    # keep only a subset of fields for the disagreements file
    out_fields = ["message_id", "thread_id", "timestamp", "reviewed", "subject", "old_label", "old_conf", "new_label", "new_conf", "method"]
    w = csv.DictWriter(outf, fieldnames=out_fields)
    w.writeheader()

    for row in r:
        total += 1
        reviewed = (row.get("reviewed") or "").strip().lower() in ("true", "1", "yes")
        old = (row.get("old_label") or "").strip()
        new = (row.get("new_label") or "").strip()
        if reviewed and old.lower() != new.lower():
            rows += 1
            out = {k: row.get(k, "") for k in out_fields}
            # Trim labels and subject for safety
            out["subject"] = (out["subject"] or "").replace("\n", " ")[:200]
            out["old_label"] = (out.get("old_label", "") or "").strip()
            out["new_label"] = (out.get("new_label", "") or "").strip()
            w.writerow(out)

print(f"Processed {total} rows; found {rows} reviewed disagreements -> {OUT}")
