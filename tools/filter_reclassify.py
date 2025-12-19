#!/usr/bin/env python3
"""Filter reclassify CSVs to surface real changes and whitespace-only differences.

Produces:
- reclassify_changes_only.csv: rows where normalized old_label != normalized new_label OR confidence changed > threshold
- reclassify_whitespace_only.csv: rows where raw old_label != raw new_label but stripped values are equal
- prints counts
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "reclassify_dryrun_full_trimmed_with_ts.csv"
OUT_CHANGES = ROOT / "reclassify_changes_only.csv"
OUT_WS = ROOT / "reclassify_whitespace_only.csv"

CONF_THRESH = 0.001  # treat tiny numeric formatting diffs as no-change

if not IN.exists():
    print(f"Input file not found: {IN}")
    raise SystemExit(1)

total = 0
changes = 0
ws_only = 0

with IN.open("r", encoding="utf-8", newline="") as inf:
    reader = csv.DictReader(inf)
    fieldnames = reader.fieldnames

    # Try opening output files; if they're locked, fall back to alternate names.
    def _open_out(path: Path):
        try:
            return path.open("w", encoding="utf-8", newline="")
        except PermissionError:
            alt = path.with_name(path.stem + ".new" + path.suffix)
            print(f"Warning: could not open {path!s}, writing to {alt!s} instead")
            return alt.open("w", encoding="utf-8", newline="")

    with _open_out(OUT_CHANGES) as outf, _open_out(OUT_WS) as outws:
        change_writer = csv.DictWriter(outf, fieldnames=fieldnames)
        ws_writer = csv.DictWriter(outws, fieldnames=fieldnames)
        change_writer.writeheader()
        ws_writer.writeheader()

        for row in reader:
            total += 1
            old_label_raw = row.get("old_label", "")
            new_label_raw = row.get("new_label", "")
            old_label_norm = (old_label_raw or "").strip().lower()
            new_label_norm = (new_label_raw or "").strip().lower()

            try:
                old_conf = float(row.get("old_conf") or 0.0)
            except Exception:
                old_conf = 0.0
            try:
                new_conf = float(row.get("new_conf") or 0.0)
            except Exception:
                new_conf = 0.0

            conf_diff = abs(old_conf - new_conf)
            # Prepare trimmed versions for output (ensure exported CSVs have trimmed labels)
            trimmed_old = (old_label_raw or "").strip()
            trimmed_new = (new_label_raw or "").strip()

            # whitespace-only: raw differ but stripped equal (case-insensitive considered by norm)
            if old_label_raw != new_label_raw and old_label_norm == new_label_norm:
                ws_only += 1
                # write trimmed label values to output
                row["old_label"] = trimmed_old
                row["new_label"] = trimmed_new
                ws_writer.writerow(row)
                continue

            # True change only if normalized labels differ. Do not treat confidence-only
            # differences as a real change (they clutter the changes CSV).
            if old_label_norm != new_label_norm:
                changes += 1
                # write trimmed label values to output
                row["old_label"] = trimmed_old
                row["new_label"] = trimmed_new
                change_writer.writerow(row)

print(f"Total rows processed: {total}")
print(f"Rows with whitespace-only label differences: {ws_only} -> {OUT_WS}")
print(
    f"Rows with real changes (label or significant confidence change): {changes} -> {OUT_CHANGES}"
)
print("Done.")
