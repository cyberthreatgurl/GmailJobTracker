"""Interactive CLI for updating CHANGELOG.md with new entries."""
import argparse
from changelog_parser import parse_changelog


def main():
    """Parse and filter CHANGELOG.md entries via CLI."""
    parser = argparse.ArgumentParser(description="Audit CHANGELOG.md entries")
    parser.add_argument('--version', help="Filter by version (e.g., 1.1.0)")
    parser.add_argument('--section', help="Filter by section (e.g., Added, Fixed, Next)")
    parser.add_argument('--keyword', help="Search for keyword in entries")
    parser.add_argument('--file', default='CHANGELOG.md', help="Path to changelog file")

    args = parser.parse_args()
    entries = parse_changelog(args.file)

    for entry in entries:
        if args.version and entry['version'] != args.version:
            continue

        print(f"\n## Version {entry['version']} ({entry['date']})")
        for section, items in entry['sections'].items():
            if args.section and section.lower() != args.section.lower():
                continue
            print(f"  ### {section}")
            for item in items:
                if args.keyword and args.keyword.lower() not in item.lower():
                    continue
                print(f"    - {item}")


if __name__ == '__main__':
    main()
