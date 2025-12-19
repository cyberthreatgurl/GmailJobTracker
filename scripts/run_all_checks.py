#!/usr/bin/env python3
"""
Run All Code Quality Checks
Convenient wrapper to run all quality analysis scripts at once.

Usage:
    python scripts/run_all_checks.py [--skip-duplicates] [--cleanup]
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(cmd: list, description: str, capture: bool = True):
    """Run a command and display results."""
    print(f"\n{'=' * 70}")
    print(f"🔍 {description}")
    print(f"{'=' * 70}")

    try:
        if capture:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            return result.returncode == 0
        else:
            result = subprocess.run(cmd, check=False)
            return result.returncode == 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run all code quality checks")
    parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Skip duplicate code analysis (can be slow)",
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="Run import cleanup (interactive)"
    )
    parser.add_argument("--output-dir", default=".", help="Directory for output files")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print("📊 GMAILJOBTRACKET CODE QUALITY ANALYSIS")
    print("=" * 70)
    print(f"Timestamp: {timestamp}")
    print(f"Project: {project_root}")
    print("=" * 70)

    results = {}

    # 1. Full code quality analysis
    report_file = f"code_quality_report_{timestamp}.json"
    success = run_command(
        [sys.executable, "scripts/analyze_code_quality.py", "--output", report_file],
        "1/4 - Comprehensive Code Quality Analysis",
    )
    results["code_quality_analysis"] = success

    # 2. Refactoring suggestions
    plan_file = f"refactor_plan_{timestamp}.txt"
    success = run_command(
        [sys.executable, "scripts/suggest_refactoring.py", "--plan"],
        "2/4 - Refactoring Suggestions",
    )
    results["refactoring_analysis"] = success

    # 3. Import analysis (dry-run)
    success = run_command(
        [sys.executable, "scripts/clean_imports.py", "--dry-run"],
        "3/4 - Unused Import Analysis",
    )
    results["import_analysis"] = success

    # 4. views.py specific analysis
    success = run_command(
        [
            sys.executable,
            "scripts/suggest_refactoring.py",
            "--file",
            "tracker/views.py",
        ],
        "4/4 - views.py Detailed Analysis",
    )
    results["views_analysis"] = success

    # Optional: Import cleanup (interactive)
    if args.cleanup:
        print("\n" + "=" * 70)
        print("🧹 OPTIONAL: Import Cleanup")
        print("=" * 70)
        response = input(
            "\nRun interactive import cleanup? This will prompt for each file. [y/N]: "
        )
        if response.lower() == "y":
            run_command(
                [sys.executable, "scripts/clean_imports.py"],
                "Import Cleanup (Interactive)",
                capture=False,
            )

    # Summary
    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)

    all_success = all(results.values())

    for check, success in results.items():
        status = "✅" if success else "❌"
        print(f"{status} {check}")

    print("\n📄 Generated Files:")
    if Path(report_file).exists():
        print(f"  - {report_file} (code quality metrics)")
    if Path("refactor_plan.txt").exists():
        print(f"  - refactor_plan.txt (refactoring suggestions)")

    print("\n💡 Next Steps:")
    print("  1. Review code_quality_report*.json for dead code and complexity")
    print("  2. Review refactor_plan.txt for file splitting suggestions")
    print("  3. Run 'python scripts/clean_imports.py' to cleanup imports")
    print("  4. Consider splitting views.py based on suggestions")
    print("  5. Re-run this script after changes to track improvements")

    print("\n" + "=" * 70)

    if all_success:
        print("✅ All checks completed successfully")
        return 0
    else:
        print("⚠️ Some checks had issues - review output above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
