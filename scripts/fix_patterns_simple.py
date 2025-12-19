#!/usr/bin/env python3
r"""
Simple pattern fixer for patterns.json

Fixes ALL pattern sections including:
- message_labels (main regex patterns)
- application, rejection, interview (legacy patterns)
- ignore, response, follow_up (legacy patterns)

Fixes applied:
1. Escaped spaces (backslash-space) -> \s
2. HTML entities (&quot;, etc.) removal
3. Plain text with spaces -> \s notation
4. Validates all patterns

Does NOT consolidate patterns - keeps structure as-is.

Usage:
    python scripts/fix_patterns_simple.py [--dry-run] [--verbose]
"""

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


def backup_file(file_path):
    """Create timestamped backup of file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = (
        file_path.parent / f"{file_path.stem}_backup_{timestamp}{file_path.suffix}"
    )
    shutil.copy2(file_path, backup_path)
    print(f"✅ Backed up to: {backup_path}")
    return backup_path


def validate_regex(pattern):
    """Validate regex pattern."""
    try:
        re.compile(pattern, re.IGNORECASE)
        return True, None
    except re.error as e:
        return False, str(e)


def fix_pattern(pattern):
    r"""
    Fix a single pattern:
    1. Remove HTML entities
    2. Convert escaped spaces (\ space) to \s
    3. Clean up
    """
    if pattern == "None":
        return pattern

    # Remove HTML entities
    pattern = pattern.replace(r"&quot;", "")
    pattern = pattern.replace(r"&amp;", "&")
    pattern = pattern.replace(r"&lt;", "<")
    pattern = pattern.replace(r"&gt;", ">")
    pattern = pattern.replace(r"&#x27;", "'")

    # Fix escaped space: backslash followed by actual space -> \s
    pattern = re.sub(r"\\\s", r"\\s", pattern)

    # Clean up multiple spaces
    pattern = re.sub(r"\s+", " ", pattern).strip()

    return pattern


def fix_patterns_file(input_path, dry_run=False, verbose=False):
    """Fix patterns in patterns.json file."""

    if not input_path.exists():
        print(f"❌ Error: {input_path} not found")
        return 1

    print(f"🔍 Loading patterns from: {input_path}")

    # Load current patterns
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stats = {"fixed": 0, "unchanged": 0, "errors": [], "sections_processed": 0}

    def process_pattern_section(section_name, patterns_dict):
        """Process a section that contains patterns (could be nested or flat)."""
        if verbose:
            print(f"\n📦 Processing section: {section_name}")

        for label, patterns in patterns_dict.items():
            if verbose:
                print(f"  📝 Label: {label}")

            if not isinstance(patterns, list):
                patterns = [patterns]

            fixed_patterns = []
            for pattern in patterns:
                # Skip non-string patterns (e.g., nested dicts, None values)
                if not isinstance(pattern, str):
                    fixed_patterns.append(pattern)
                    stats["unchanged"] += 1
                    continue

                fixed = fix_pattern(pattern)

                # Validate regex patterns (skip validation for plain text in some sections)
                if fixed != "None":
                    is_valid, error = validate_regex(fixed)
                    if not is_valid:
                        stats["errors"].append(
                            f"{section_name}.{label}: {pattern} -> {error}"
                        )
                        if verbose:
                            print(f"    ❌ Invalid regex: {pattern}")
                            print(f"       Error: {error}")
                        # Keep original if fixed version is invalid
                        fixed_patterns.append(pattern)
                        stats["unchanged"] += 1
                        continue

                if fixed != pattern:
                    stats["fixed"] += 1
                    if verbose:
                        print(f"    ✅ BEFORE: {pattern}")
                        print(f"       AFTER:  {fixed}")
                else:
                    stats["unchanged"] += 1
                    if verbose:
                        print(f"    ⏭️  Kept: {pattern}")

                fixed_patterns.append(fixed)

            patterns_dict[label] = fixed_patterns

        stats["sections_processed"] += 1

    # Process all sections that contain patterns
    pattern_sections = [
        "message_labels",  # Main regex patterns
        "application",  # Legacy patterns
        "rejection",
        "interview",
        "ignore",
        "response",
        "follow_up",
    ]

    for section in pattern_sections:
        if section in data and isinstance(data[section], dict):
            process_pattern_section(section, data[section])
        elif section in data and isinstance(data[section], list):
            # Handle flat list of patterns (like old-style top-level keys)
            if verbose:
                print(f"\n📦 Processing section: {section} (flat list)")

            fixed_list = []
            for pattern in data[section]:
                if not isinstance(pattern, str):
                    fixed_list.append(pattern)
                    stats["unchanged"] += 1
                    continue

                fixed = fix_pattern(pattern)

                # Validate
                if fixed != "None":
                    is_valid, error = validate_regex(fixed)
                    if not is_valid:
                        stats["errors"].append(f"{section}: {pattern} -> {error}")
                        if verbose:
                            print(f"  ❌ Invalid regex: {pattern}")
                            print(f"     Error: {error}")
                        fixed_list.append(pattern)
                        stats["unchanged"] += 1
                        continue

                if fixed != pattern:
                    stats["fixed"] += 1
                    if verbose:
                        print(f"  ✅ BEFORE: {pattern}")
                        print(f"     AFTER:  {fixed}")
                else:
                    stats["unchanged"] += 1
                    if verbose:
                        print(f"  ⏭️  Kept: {pattern}")

                fixed_list.append(fixed)

            data[section] = fixed_list
            stats["sections_processed"] += 1

    # Print statistics
    print("\n📊 Statistics:")
    print(f"  📦 Sections processed: {stats['sections_processed']}")
    print(f"  ✅ Fixed: {stats['fixed']} patterns")
    print(f"  ⏭️  Unchanged: {stats['unchanged']} patterns")

    if stats["errors"]:
        print(f"\n  ❌ Validation Errors: {len(stats['errors'])}")
        for error in stats["errors"][:5]:  # Show first 5
            print(f"     {error}")
        if len(stats["errors"]) > 5:
            print(f"     ... and {len(stats['errors']) - 5} more")

    # Save or dry-run
    if dry_run:
        print("\n🔍 DRY RUN - No changes saved")
        print("\n📄 Preview of fixed patterns:")
        for label in ["referral", "job_alert", "head_hunter"]:
            if label in data.get("message_labels", {}):
                print(f"\n  {label}:")
                for p in data["message_labels"][label]:
                    print(f"    {p}")
        print("\nTo apply changes, run without --dry-run")
        return 0

    # Backup original
    backup_path = backup_file(input_path)

    # Save fixed patterns
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved fixed patterns to: {input_path}")

    if stats["errors"]:
        print("\n⚠️  Some patterns had validation errors")
        print(f"   Original backup saved to: {backup_path}")
        return 1

    print("\n✨ Fix complete!")
    print("\nNext steps:")
    print("  1. Review patterns in JSON file viewer (/admin/json_file_viewer/)")
    print("  2. Test in Label Rule Debugger (/debug/label_rule/)")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Fix patterns in patterns.json")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without saving"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed info"
    )
    parser.add_argument("--input", default="json/patterns.json", help="Input file path")

    args = parser.parse_args()

    return fix_patterns_file(
        Path(args.input), dry_run=args.dry_run, verbose=args.verbose
    )


if __name__ == "__main__":
    exit(main())
