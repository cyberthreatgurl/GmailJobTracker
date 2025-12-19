#!/usr/bin/env python3
"""Parse dry-run output and export reclassify_dryrun_report.csv"""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
input_path = root / "output.txt"
out_path = root / "reclassify_dryrun_report.csv"

text = input_path.read_text(encoding="utf-8")
lines = text.splitlines()

header_re = re.compile(r"^[ \t]*[^\[]*\[([0-9]+)\/6330\]\s*(.*)$")
label_re = re.compile(
    r"^[ \t]*([a-z_]+)\(([0-9.]+)\)\s*→\s*([a-z_]+)\(([0-9.]+)\)\s*\[([^\]]+)\]"
)

records = []
for idx, line in enumerate(lines):
    m = header_re.match(line)
    if m:
        seq = m.group(1)
        subject = m.group(2).strip()
        # find next non-empty line with arrow
        before = after = reason = ""
        for j in range(idx + 1, min(idx + 6, len(lines))):
            l = lines[j].strip()
            if "→" in l:
                mm = label_re.match(lines[j])
                if mm:
                    before = mm.group(1)
                    before_conf = mm.group(2)
                    after = mm.group(3)
                    after_conf = mm.group(4)
                    reason = mm.group(5)
                else:
                    # fallback: try to extract labels without strict regex
                    parts = l.split("→")
                    if len(parts) == 2:
                        left = parts[0].strip()
                        right = parts[1].strip()
                        # left like noise(0.99)
                        bl = re.match(r"([a-z_]+)\(([0-9.]+)\)", left)
                        ar = re.match(r"([a-z_]+)\(([0-9.]+)\)", right)
                        before = bl.group(1) if bl else ""
                        before_conf = bl.group(2) if bl else ""
                        after = ar.group(1) if ar else ""
                        after_conf = ar.group(2) if ar else ""
                        rr = re.search(r"\[([^\]]+)\]", l)
                        reason = rr.group(1) if rr else ""
                records.append(
                    {
                        "seq": seq,
                        "subject": subject,
                        "before": before,
                        "before_conf": before_conf,
                        "after": after,
                        "after_conf": after_conf,
                        "reason": reason,
                    }
                )
                break

# write CSV
with out_path.open("w", encoding="utf-8") as f:
    f.write("seq,subject,before,before_conf,after,after_conf,reason\n")
    for r in records:
        # escape commas in subject
        subj = '"' + r["subject"].replace('"', '""') + '"'
        f.write(
            f"{r['seq']},{subj},{r['before']},{r['before_conf']},{r['after']},{r['after_conf']},{r['reason']}\n"
        )

print(f"Wrote {len(records)} records to {out_path}")
