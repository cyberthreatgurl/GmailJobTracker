"""
Import Gmail filters (XML) and update json/patterns.json message_labels with regexes derived from filters.

Usage (from repo root):
  python -m scripts.import_gmail_filters --filters path/to/mailFilters.xml \
      [--map json/gmail_label_map.json] [--patterns json/patterns.json] [--dry-run]

Notes:
- We map Gmail label names to internal labels via gmail_label_map.json
- From each filter, we use 'subject' and 'hasTheWord' properties to create simple regex OR patterns
- We dedupe and append to existing patterns.json.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def load_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def sanitize_to_regex_terms(text: str) -> list[str]:
    """Convert a Gmail query-like string into a list of regex-safe terms.
    This is a heuristic: split on whitespace and common separators; keep words >= 3 chars.
    """
    if not text:
        return []
    # Remove Gmail search operators likely to break regex
    cleaned = re.sub(
        r"(label:|from:|to:|subject:|in:|is:|has:|before:|after:)",
        " ",
        text,
        flags=re.I,
    )
    # Split on non-word boundaries but keep basic words and phrases in quotes
    quoted = re.findall(r'"([^"]+)"', cleaned)
    for q in quoted:
        cleaned = cleaned.replace(f'"{q}"', " ")
    parts = re.split(r"[^A-Za-z0-9@._'+-]+", cleaned)
    terms = [t for t in parts if len(t) >= 3]
    terms.extend([q for q in quoted if len(q) >= 3])
    # Dedup while preserving order
    seen = set()
    out = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(re.escape(t))
    return out


def make_or_pattern(terms: list[str]) -> str | None:
    if not terms:
        return None
    # Wrap in word boundaries when terms are pure words; otherwise leave as is
    # We keep it simple: use alternation
    return r"(" + r"|".join(terms) + r")"


def parse_filters(xml_path: Path):
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "apps": "http://schemas.google.com/apps/2006",
    }
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for entry in root.findall("atom:entry", ns):
        props = {}
        for p in entry.findall("apps:property", ns):
            name = p.attrib.get("name")
            val = p.attrib.get("value", "")
            if name:
                props[name] = val
        yield props


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--filters", required=True, help="Path to Gmail filters XML (mailFilters.xml)"
    )
    ap.add_argument(
        "--map",
        default="json/gmail_label_map.json",
        help="Gmail->internal label map JSON",
    )
    ap.add_argument(
        "--patterns", default="json/patterns.json", help="patterns.json path to update"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Print proposed changes without writing"
    )
    args = ap.parse_args()

    filters_path = Path(args.filters)
    label_map_path = Path(args.map)
    patterns_path = Path(args.patterns)

    if not filters_path.exists():
        print(f"[Error] Filters file not found: {filters_path}")
        sys.exit(1)

    label_map = load_json(label_map_path, default={})
    patterns = load_json(patterns_path, default={"message_labels": {}})
    msg_labels = patterns.setdefault("message_labels", {})

    additions = {}
    exclude_additions = {}
    skipped = 0
    for props in parse_filters(filters_path):
        gmail_label = props.get("label") or props.get("shouldApplyLabel")
        if not gmail_label:
            continue
        internal = label_map.get(gmail_label)
        if not internal:
            skipped += 1
            continue
        terms = []
        for key in ("subject", "hasTheWord"):
            terms += sanitize_to_regex_terms(props.get(key, ""))
        pattern = make_or_pattern(terms)
        if not pattern:
            continue
        additions.setdefault(internal, set()).add(pattern)
        # Handle doesNotHaveTheWord -> exclusions
        ex_terms = sanitize_to_regex_terms(props.get("doesNotHaveTheWord", ""))
        ex_pattern = make_or_pattern(ex_terms)
        if ex_pattern:
            exclude_additions.setdefault(internal, set()).add(ex_pattern)

    # Apply to patterns.json
    for label, new_set in additions.items():
        existing = set(msg_labels.get(label, []))
        combined = sorted(existing.union(new_set))
        msg_labels[label] = combined

    # Apply excludes into message_label_excludes
    msg_excludes = patterns.setdefault("message_label_excludes", {})
    for label, new_set in exclude_additions.items():
        existing = set(msg_excludes.get(label, []))
        combined = sorted(existing.union(new_set))
        msg_excludes[label] = combined

    if args.dry_run:
        print(json.dumps(patterns, indent=2))
        print(
            f"[Dry-run] Would update {len(additions)} labels (with excludes for {len(exclude_additions)}); skipped {skipped} filters with unmapped labels."
        )
        return

    # Write back
    patterns_path.parent.mkdir(parents=True, exist_ok=True)
    with open(patterns_path, "w", encoding="utf-8") as f:
        json.dump(patterns, f, indent=2, ensure_ascii=False)
    print(
        f"[OK] Updated {patterns_path} with Gmail-derived patterns. Skipped {skipped} unmapped filters."
    )


if __name__ == "__main__":
    main()
