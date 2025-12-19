#!/usr/bin/env python3
"""Extract specific functions from views_legacy.py with their decorators."""

import sys
from pathlib import Path

# Map function names to their line ranges (start line, decorator line if any)
FUNCTION_RANGES = {
    # API module
    "ingestion_status_api": (3480, 3500),
    # Helpers module
    "build_sidebar_context": (1032, 1040),
    "extract_body_content": (2017, 2030),
    "validate_regex_pattern": (2866, 2904),
    "sanitize_string": (2905, 2962),
    "validate_domain": (2963, 2994),
    "_parse_pasted_gmail_spec": (3501, 3555),
}


def extract_lines(filepath, start, end):
    """Extract lines from start to end (inclusive)."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[start - 1 : end])


def main():
    legacy_file = Path("tracker/views_legacy.py")

    for func_name, (start, end) in FUNCTION_RANGES.items():
        print(f"{func_name}: lines {start}-{end}")
        code = extract_lines(legacy_file, start, end)
        print(code[:200])
        print("---")


if __name__ == "__main__":
    main()
