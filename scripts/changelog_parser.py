"""Parser for CHANGELOG.md entries following Keep a Changelog format."""

import re
from collections import defaultdict


def parse_changelog(path="CHANGELOG.md"):
    """Parse CHANGELOG.md and return list of entries by version/section."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    changelog = []
    current_entry = {}
    current_section = None

    version_pattern = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})")
    section_pattern = re.compile(r"^### (\w+)")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        version_match = version_pattern.match(line)
        if version_match:
            if current_entry:
                changelog.append(current_entry)
            current_entry = {
                "version": version_match.group(1),
                "date": version_match.group(2),
                "sections": defaultdict(list),
            }
            current_section = None
            continue

        section_match = section_pattern.match(line)
        if section_match:
            current_section = section_match.group(1)
            continue

        if current_section and current_entry:
            current_entry["sections"][current_section].append(line.lstrip("- ").strip())

    if current_entry:
        changelog.append(current_entry)

    return changelog
