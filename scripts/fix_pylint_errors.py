"""
Automated script to fix common pylint errors systematically.
This script processes the pylint report and applies automated fixes.

Usage:
    python scripts/fix_pylint_errors.py --category <category> [--dry-run]

Categories:
    - imports: Fix import ordering, unused imports, reimports
    - formatting: Fix line length, trailing whitespace, final newlines
    - docstrings: Add missing module/function docstrings
    - all: Run all automated fixes
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


class PylintFixer:
    """Automated fixer for common pylint errors."""

    def __init__(self, report_path: str, dry_run: bool = False):
        self.report_path = Path(report_path)
        self.dry_run = dry_run
        self.errors = self._load_errors()
        self.errors_by_file = self._group_by_file()
        self.fixed_count = 0

    def _load_errors(self) -> List[Dict]:
        """Load pylint errors from JSON report."""
        with open(self.report_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _group_by_file(self) -> Dict[str, List[Dict]]:
        """Group errors by file path."""
        grouped = defaultdict(list)
        for error in self.errors:
            path = error.get("path", "")
            if path:
                grouped[path].append(error)
        return grouped

    def fix_missing_final_newline(self):
        """Add final newline to files missing it."""
        print("\n🔧 Fixing missing final newlines...")

        for error in self.errors:
            if error["symbol"] == "missing-final-newline":
                filepath = Path(error["path"])
                if not filepath.exists():
                    continue

                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                if not content.endswith("\n"):
                    if not self.dry_run:
                        with open(filepath, "a", encoding="utf-8") as f:
                            f.write("\n")
                    print(f"  ✓ {filepath}")
                    self.fixed_count += 1

    def fix_trailing_whitespace(self):
        """Remove trailing whitespace from lines."""
        print("\n🔧 Fixing trailing whitespace...")

        files_with_trailing = set()
        for error in self.errors:
            if error["symbol"] == "trailing-whitespace":
                files_with_trailing.add(error["path"])

        for filepath_str in files_with_trailing:
            filepath = Path(filepath_str)
            if not filepath.exists():
                continue

            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            fixed_lines = [
                line.rstrip() + "\n" if line.endswith("\n") else line.rstrip()
                for line in lines
            ]

            if lines != fixed_lines:
                if not self.dry_run:
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.writelines(fixed_lines)
                print(f"  ✓ {filepath}")
                self.fixed_count += 1

    def fix_unused_imports(self):
        """Remove unused imports (requires careful analysis)."""
        print("\n🔧 Fixing unused imports...")
        print("  ℹ️  This is best done with autoflake or manual review")
        print("  Run: autoflake --remove-all-unused-imports --in-place <file>")

        unused_by_file = defaultdict(list)
        for error in self.errors:
            if error["symbol"] == "unused-import":
                unused_by_file[error["path"]].append(error)

        for filepath, errors in unused_by_file.items():
            print(f"  📄 {filepath}: {len(errors)} unused imports")

    def generate_import_fix_commands(self):
        """Generate commands to fix import ordering."""
        print("\n🔧 To fix import ordering, run:")

        files_with_import_issues = set()
        for error in self.errors:
            if error["symbol"] in (
                "wrong-import-order",
                "wrong-import-position",
                "ungrouped-imports",
                "reimported",
            ):
                files_with_import_issues.add(error["path"])

        print("  # Install isort if not already installed")
        print("  pip install isort")
        print("\n  # Fix all import issues:")
        for filepath in sorted(files_with_import_issues):
            if Path(filepath).exists():
                print(f"  isort {filepath}")

    def add_module_docstrings(self):
        """Add missing module docstrings."""
        print("\n🔧 Adding missing module docstrings...")

        for error in self.errors:
            if error["symbol"] == "missing-module-docstring" and error["line"] == 1:
                filepath = Path(error["path"])
                if not filepath.exists() or filepath.suffix != ".py":
                    continue

                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                # Skip if already has a docstring
                if content.strip().startswith('"""') or content.strip().startswith(
                    "'''"
                ):
                    continue

                # Generate docstring based on filename
                module_name = filepath.stem.replace("_", " ").title()
                docstring = f'"""\n{module_name} module for GmailJobTracker.\n"""\n\n'

                if not self.dry_run:
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(docstring + content)

                print(f"  ✓ {filepath}")
                self.fixed_count += 1

    def fix_broad_exceptions(self):
        """Report broad exception catches that need manual review."""
        print("\n🔧 Broad exception catches (requires manual review):")

        broad_by_file = defaultdict(list)
        for error in self.errors:
            if error["symbol"] == "broad-exception-caught":
                broad_by_file[error["path"]].append(error)

        for filepath, errors in sorted(broad_by_file.items()):
            print(f"\n  📄 {filepath}:")
            for error in errors:
                print(f"    Line {error['line']}: {error['message']}")
                print(f"    → Consider catching specific exceptions instead")

    def show_import_errors(self):
        """Show import errors that need fixing."""
        print("\n❌ Import errors (requires investigation):")

        import_errors = defaultdict(list)
        for error in self.errors:
            if error["symbol"] == "import-error":
                import_errors[error["path"]].append(error)

        for filepath, errors in sorted(import_errors.items()):
            print(f"\n  📄 {filepath}:")
            for error in errors:
                print(f"    Line {error['line']}: {error['message']}")

    def show_summary(self):
        """Show summary of all errors."""
        print("\n" + "=" * 70)
        print("📊 PYLINT ERROR SUMMARY")
        print("=" * 70)

        error_counts = defaultdict(int)
        for error in self.errors:
            error_counts[error["symbol"]] += 1

        print(f"\nTotal errors: {len(self.errors)}")
        print(f"\nTop 20 error types:")
        for symbol, count in sorted(error_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  {symbol:40s}: {count:4d}")

        print(f"\nTotal files with errors: {len(self.errors_by_file)}")

    def run_formatting_fixes(self):
        """Run all formatting-related fixes."""
        print("\n🚀 Running formatting fixes...")
        self.fix_missing_final_newline()
        self.fix_trailing_whitespace()

        if self.dry_run:
            print(f"\n✓ Would fix {self.fixed_count} formatting issues (dry run)")
        else:
            print(f"\n✓ Fixed {self.fixed_count} formatting issues")

    def run_docstring_fixes(self):
        """Run docstring-related fixes."""
        print("\n🚀 Running docstring fixes...")
        self.add_module_docstrings()

        if self.dry_run:
            print(f"\n✓ Would add {self.fixed_count} module docstrings (dry run)")
        else:
            print(f"\n✓ Added {self.fixed_count} module docstrings")

    def run_all_automated_fixes(self):
        """Run all safe automated fixes."""
        self.run_formatting_fixes()
        self.add_module_docstrings()

        print("\n" + "=" * 70)
        print("✅ Automated fixes complete!")
        print("=" * 70)

        if not self.dry_run:
            print(f"\nTotal issues fixed: {self.fixed_count}")

        print("\n📋 Next steps for remaining errors:")
        print("  1. Run isort to fix import ordering")
        print("  2. Run autoflake to remove unused imports")
        print("  3. Run black for code formatting")
        print("  4. Manually review broad exception catches")
        print("  5. Fix import errors")
        print("  6. Add function docstrings where needed")


def main():
    parser = argparse.ArgumentParser(
        description="Automated pylint error fixer for GmailJobTracker"
    )
    parser.add_argument(
        "--category",
        choices=["formatting", "docstrings", "imports", "summary", "all"],
        default="summary",
        help="Category of fixes to apply",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes",
    )
    parser.add_argument(
        "--report",
        default="scripts/debug/pylint_report.json",
        help="Path to pylint JSON report",
    )

    args = parser.parse_args()

    fixer = PylintFixer(args.report, dry_run=args.dry_run)

    if args.category == "summary":
        fixer.show_summary()
    elif args.category == "formatting":
        fixer.run_formatting_fixes()
    elif args.category == "docstrings":
        fixer.run_docstring_fixes()
    elif args.category == "imports":
        fixer.generate_import_fix_commands()
        fixer.fix_unused_imports()
        fixer.show_import_errors()
    elif args.category == "all":
        fixer.run_all_automated_fixes()
        fixer.generate_import_fix_commands()


if __name__ == "__main__":
    main()
