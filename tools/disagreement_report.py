#!/usr/bin/env python3
"""Produce summaries from `reviewed_disagreements.csv`.

Outputs:
- review_reports/disagreement_by_pair.csv
- review_reports/disagreement_by_old_label.csv
- review_reports/disagreement_by_new_label.csv
- review_reports/disagreement_by_method.csv

Also prints the top 20 label-pair disagreements to stdout.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_DIR = ROOT / "review_reports"
IN = IN_DIR / "reviewed_disagreements.csv"
OUT_DIR = IN_DIR
OUT_DIR.mkdir(exist_ok=True)

if not IN.exists():
    print(f"Input not found: {IN}")
    raise SystemExit(1)

pair_counter = Counter()
old_counter = Counter()
new_counter = Counter()
method_counter = Counter()

total = 0
with IN.open("r", encoding="utf-8", newline="") as inf:
    r = csv.DictReader(inf)
    for row in r:
        total += 1
        old = (row.get("old_label") or "").strip() or "(blank)"
        new = (row.get("new_label") or "").strip() or "(blank)"
        method = (row.get("method") or "").strip() or "(unknown)"
        pair_counter[(old, new)] += 1
        old_counter[old] += 1
        new_counter[new] += 1
        method_counter[method] += 1


def write_counter(counter, outpath, headers):
    with outpath.open("w", encoding="utf-8", newline="") as outf:
        w = csv.writer(outf)
        w.writerow(headers)
        for k, v in counter.most_common():
            if isinstance(k, tuple):
                w.writerow([*k, v])
            else:
                w.writerow([k, v])


write_counter(
    pair_counter,
    OUT_DIR / "disagreement_by_pair.csv",
    ["old_label", "new_label", "count"],
)
write_counter(
    old_counter, OUT_DIR / "disagreement_by_old_label.csv", ["old_label", "count"]
)
write_counter(
    new_counter, OUT_DIR / "disagreement_by_new_label.csv", ["new_label", "count"]
)
write_counter(
    method_counter, OUT_DIR / "disagreement_by_method.csv", ["method", "count"]
)

print(f"Processed {total} reviewed-disagreement rows")
print("Top 20 label-pair disagreements:")
for (old, new), cnt in pair_counter.most_common(20):
    pct = cnt / total * 100 if total else 0
    print(f"{cnt:5d} ({pct:5.2f}%)  {old!r}  ->  {new!r}")

print("\nTop old labels (how many reviewed messages disagree):")
for lbl, cnt in old_counter.most_common(10):
    print(f"{cnt:5d}  {lbl!r}")

print("\nTop new (ML) labels suggested:")
for lbl, cnt in new_counter.most_common(10):
    print(f"{cnt:5d}  {lbl!r}")

print("\nDisagreements by method:")
for m, cnt in method_counter.most_common():
    print(f"{cnt:5d}  {m!r}")

print(f"\nWrote CSV summaries to {OUT_DIR}")
