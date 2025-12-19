#!/usr/bin/env python3
"""
Safe Import Cleaner
Removes unused imports from Python files after confirmation.

Usage:
    python scripts/clean_imports.py [--dry-run] [--file tracker/views.py]
"""

import ast
import re
from pathlib import Path
from typing import List, Set, Tuple


def extract_imports(content: str) -> List[Tuple[str, str, int]]:
    """Extract all imports with their line numbers.

    Returns: [(import_name, full_line, line_number), ...]
    """
    imports = []
    lines = content.splitlines()

    for i, line in enumerate(lines, 1):
        # Simple import: import foo, bar
        match = re.match(r"^import\s+([\w\s,]+)", line)
        if match:
            names = match.group(1).split(",")
            for name in names:
                name = name.strip().split(" as ")[0].strip()
                imports.append((name, line, i))
            continue

        # From import: from foo import bar, baz
        match = re.match(r"^from\s+([\w.]+)\s+import\s+([\w\s,]+)", line)
        if match:
            names = match.group(2).split(",")
            for name in names:
                name = name.strip().split(" as ")[0].strip()
                imports.append((name, line, i))

    return imports


def is_import_used(import_name: str, content: str, import_line_num: int) -> bool:
    """Check if an import is actually used in the file."""
    lines = content.splitlines()

    # Special cases: always keep certain imports
    essential_imports = {
        "django",
        "models",
        "forms",
        "admin",
        "Q",
        "F",
        "Count",
        "Sum",
        "login_required",
        "csrf_exempt",
        "render",
        "redirect",
        "JsonResponse",
        "HttpResponse",
        "StreamingHttpResponse",
        "os",
        "sys",
        "re",
        "json",
        "Path",
        "datetime",
        "timedelta",
        "settings",
    }

    if import_name in essential_imports:
        return True

    # Check if import appears elsewhere in file (excluding the import line itself)
    pattern = rf"\b{re.escape(import_name)}\b"

    for i, line in enumerate(lines, 1):
        if i == import_line_num:
            continue  # Skip the import line itself

        # Skip comments
        if line.strip().startswith("#"):
            continue

        # Check for usage
        if re.search(pattern, line):
            return True

    return False


def find_unused_imports(filepath: Path, verbose: bool = False) -> List[Tuple[int, str]]:
    """Find unused imports in a Python file.

    Returns: [(line_number, import_line), ...]
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    imports = extract_imports(content)
    unused = []

    for import_name, import_line, line_num in imports:
        if not is_import_used(import_name, content, line_num):
            unused.append((line_num, import_line.strip()))
            if verbose:
                print(f"  Line {line_num}: {import_name} appears unused")

    return unused


def remove_unused_imports(filepath: Path, dry_run: bool = True) -> int:
    """Remove unused imports from file.

    Returns: number of imports removed
    """
    unused = find_unused_imports(filepath, verbose=dry_run)

    if not unused:
        print(f"✅ {filepath.name}: No unused imports found")
        return 0

    print(f"\n⚠️ {filepath.name}: Found {len(unused)} potentially unused imports:")
    for line_num, import_line in unused:
        print(f"  Line {line_num}: {import_line}")

    if dry_run:
        print("  (DRY RUN - no changes made)")
        return 0

    # Ask for confirmation
    response = input(f"\nRemove these {len(unused)} imports? [y/N]: ")
    if response.lower() != "y":
        print("  Skipped")
        return 0

    # Remove the imports
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Sort by line number in reverse to avoid index shifting
    unused_lines = {line_num for line_num, _ in unused}
    new_lines = [line for i, line in enumerate(lines, 1) if i not in unused_lines]

    # Write back
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"  ✅ Removed {len(unused)} imports")
    return len(unused)


def clean_project_imports(project_root: Path, dry_run: bool = True):
    """Clean imports across all Python files in project."""
    print("🧹 Cleaning unused imports...")
    print("=" * 60)

    py_files = list(project_root.rglob("*.py"))
    py_files = [
        f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)
    ]

    total_removed = 0
    files_affected = 0

    for py_file in sorted(py_files):
        rel_path = py_file.relative_to(project_root)
        removed = remove_unused_imports(py_file, dry_run)
        if removed > 0:
            files_affected += 1
            total_removed += removed

    print("\n" + "=" * 60)
    print(f"📊 Summary:")
    print(f"  Files scanned: {len(py_files)}")
    print(f"  Files with unused imports: {files_affected}")
    print(f"  Total unused imports: {total_removed}")

    if dry_run:
        print(f"\n💡 Run without --dry-run to actually remove imports")
    else:
        print(f"\n✅ Cleanup complete!")

    print("=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Clean unused imports")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without making changes",
    )
    parser.add_argument("--file", help="Clean specific file only")
    parser.add_argument("--verbose", action="store_true", help="Show detailed analysis")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    if args.file:
        filepath = project_root / args.file
        if filepath.exists():
            remove_unused_imports(filepath, args.dry_run)
        else:
            print(f"❌ File not found: {args.file}")
    else:
        clean_project_imports(project_root, args.dry_run)


if __name__ == "__main__":
    main()
