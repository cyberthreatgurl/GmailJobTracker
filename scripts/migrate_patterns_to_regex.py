#!/usr/bin/env python3
"""
Migrate patterns.json to use standard regex syntax.

This script:
1. Backs up the existing patterns.json
2. Converts plain text patterns to proper regex
3. Fixes spacing issues (\ space -> \s)
4. Removes HTML entities (&quot;)
5. Consolidates multiple simple patterns into OR patterns
6. Validates all regex patterns
7. Saves the migrated file

Usage:
    python scripts/migrate_patterns_to_regex.py [--dry-run] [--verbose]
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


def escape_literal_text(text):
    """
    Escape special regex characters in literal text.
    Only escape if text doesn't already look like a regex pattern.
    """
    # Check if it already looks like a regex (has regex special chars in meaningful way)
    has_word_boundary = r"\b" in text
    has_char_class = re.search(r"\[.*?\]", text) or re.search(r"\(.*?\|.*?\)", text)
    has_quantifiers = any(q in text for q in ["*", "+", "?", "{"])

    if has_word_boundary or has_char_class or has_quantifiers:
        # Already a regex pattern, don't escape
        return text

    # Escape regex special characters for literal matching
    special_chars = r".^$*+?{}[]()|\\"
    escaped = ""
    for char in text:
        if char in special_chars:
            escaped += "\\" + char
        else:
            escaped += char

    return escaped


def convert_plain_text_to_regex(pattern):
    """
    Convert plain text pattern to proper regex.

    Handles:
    - Plain text with spaces -> proper regex with \s
    - Removes HTML entities like &quot;
    - Fixes escaped spaces (\ space -> \s)
    - Ensures word boundaries where appropriate
    """
    # Remove HTML entities
    pattern = pattern.replace("&quot;", "")
    pattern = pattern.replace("&amp;", "&")
    pattern = pattern.replace("&lt;", "<")
    pattern = pattern.replace("&gt;", ">")

    # Fix escaped space: \ (space) -> \s
    pattern = re.sub(r"\\\s+", r"\\s", pattern)

    # Clean up extra spaces that might have been left
    pattern = re.sub(r"\s+", " ", pattern).strip()

    # If pattern has parentheses and already looks like regex, just return it
    if pattern.startswith("(") and pattern.endswith(")"):
        # Already has grouping, return as-is
        return pattern
    elif "|" in pattern:
        # Has OR but no grouping, add it only if needed
        if not (pattern.startswith("(") and pattern.endswith(")")):
            pattern = f"({pattern})"
    else:
        # Plain text pattern - check if it's already a regex pattern
        if not any(
            marker in pattern
            for marker in [r"\b", r"\s", r"\d", r"\\", "[", "]", "*", "+", "?"]
        ):
            # Plain text with possible spaces
            if " " in pattern:
                # Multi-word phrase: replace spaces with \s
                pattern = pattern.replace(" ", r"\s")
            # No word boundaries by default - let user add if needed

    return pattern


def consolidate_simple_patterns(patterns):
    """
    Consolidate multiple simple text patterns into a single OR pattern.
    Only consolidates if all patterns are simple (no regex special chars).
    """
    if len(patterns) <= 1:
        return patterns

    # Check if all patterns are simple text (no regex markers)
    all_simple = True
    for p in patterns:
        if p == "None":
            continue
        # Check for regex special constructs
        if any(
            marker in p
            for marker in [
                r"\b",
                r"\s",
                r"\d",
                "|",
                "[",
                "]",
                "(",
                ")",
                "*",
                "+",
                "?",
                "{",
                "}",
            ]
        ):
            all_simple = False
            break

    if not all_simple:
        # Mix of simple and complex patterns, keep as-is
        return patterns

    # All simple - consolidate into OR pattern
    # Escape each pattern and join with |
    escaped_patterns = []
    for p in patterns:
        if p == "None":
            continue
        # Escape special chars, replace spaces with \s
        escaped = escape_literal_text(p)
        if " " in p:
            escaped = escaped.replace(" ", r"\s")
        escaped_patterns.append(escaped)

    if not escaped_patterns:
        return ["None"]

    # Create OR pattern
    consolidated = "|".join(escaped_patterns)

    return [consolidated]


def migrate_patterns(patterns_data, verbose=False):
    """
    Migrate patterns to standard regex format.
    """
    migrated = {}
    stats = {"converted": 0, "consolidated": 0, "kept_as_is": 0, "errors": []}

    # Migrate message_labels
    if "message_labels" in patterns_data:
        migrated["message_labels"] = {}

        for label, patterns in patterns_data["message_labels"].items():
            if verbose:
                print(f"\n📝 Processing label: {label}")

            # Skip if already "None"
            if patterns == ["None"] or patterns == "None":
                migrated["message_labels"][label] = ["None"]
                if verbose:
                    print(f"  ⏭️  Skipped (None)")
                stats["kept_as_is"] += 1
                continue

            if not isinstance(patterns, list):
                patterns = [patterns]

            # Try to consolidate simple patterns
            original_count = len(patterns)
            consolidated = consolidate_simple_patterns(patterns)

            if len(consolidated) < original_count:
                stats["consolidated"] += 1
                if verbose:
                    print(
                        f"  🔄 Consolidated {original_count} patterns into {len(consolidated)}"
                    )

            # Convert each pattern
            migrated_patterns = []
            for pattern in consolidated:
                if pattern == "None":
                    migrated_patterns.append("None")
                    continue

                # Convert to regex
                converted = convert_plain_text_to_regex(pattern)

                # Validate
                is_valid, error = validate_regex(converted)
                if not is_valid:
                    stats["errors"].append(f"{label}: {pattern} -> {error}")
                    if verbose:
                        print(f"  ❌ Invalid regex: {pattern} -> {error}")
                    # Keep original if conversion failed
                    migrated_patterns.append(pattern)
                else:
                    migrated_patterns.append(converted)
                    stats["converted"] += 1
                    if verbose and pattern != converted:
                        print(f"  ✅ {pattern}")
                        print(f"     -> {converted}")
                    elif verbose:
                        print(f"  ⏭️  Kept: {pattern}")

            migrated["message_labels"][label] = migrated_patterns

    # Copy other sections as-is
    for key in patterns_data:
        if key not in ["message_labels"]:
            migrated[key] = patterns_data[key]

    return migrated, stats


def main():
    parser = argparse.ArgumentParser(
        description="Migrate patterns.json to standard regex format"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without saving"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed conversion info"
    )
    parser.add_argument("--input", default="json/patterns.json", help="Input file path")
    parser.add_argument("--output", help="Output file path (default: overwrites input)")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        print(f"❌ Error: {input_path} not found")
        return 1

    print(f"🔍 Loading patterns from: {input_path}")

    # Load current patterns
    with open(input_path, "r", encoding="utf-8") as f:
        patterns_data = json.load(f)

    # Migrate patterns
    print("\n🔄 Migrating patterns to standard regex format...")
    migrated_data, stats = migrate_patterns(patterns_data, verbose=args.verbose)

    # Print statistics
    print("\n📊 Migration Statistics:")
    print(f"  ✅ Converted: {stats['converted']} patterns")
    print(f"  🔄 Consolidated: {stats['consolidated']} labels")
    print(f"  ⏭️  Kept as-is: {stats['kept_as_is']} patterns")

    if stats["errors"]:
        print(f"\n  ❌ Errors: {len(stats['errors'])}")
        for error in stats["errors"]:
            print(f"     {error}")

    # Show preview
    if args.verbose or args.dry_run:
        print("\n📄 Migrated patterns preview:")
        print(
            json.dumps(migrated_data.get("message_labels", {}), indent=2)[:1000] + "..."
        )

    # Save or dry-run
    if args.dry_run:
        print("\n🔍 DRY RUN - No changes saved")
        print(f"   To apply changes, run without --dry-run")
        return 0

    # Backup original
    if not args.output:  # Only backup if overwriting
        backup_file(input_path)

    # Save migrated patterns
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(migrated_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved migrated patterns to: {output_path}")

    if stats["errors"]:
        print("\n⚠️  Some patterns had validation errors and were kept as-is")
        print("   Please review and fix manually")
        return 1

    print("\n✨ Migration complete!")
    print("\nNext steps:")
    print("  1. Review the migrated patterns in the JSON file viewer")
    print("  2. Test patterns in the Label Rule Debugger (/debug/label_rule/)")
    print("  3. Consider retraining the ML model")
    print(
        "  4. Re-ingest messages: python manage.py ingest_gmail --force --days-back 7"
    )

    return 0


if __name__ == "__main__":
    exit(main())
