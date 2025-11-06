#!/usr/bin/env python3
"""
Helper script to list Gmail labels and their IDs
Run this to find your GMAIL_JOBHUNT_LABEL_ID
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from gmail_auth import get_gmail_service
except ImportError:
    print("❌ Error: Could not import gmail_auth module")
    print("Make sure you're running this from the project directory")
    sys.exit(1)


def list_labels():
    """List all Gmail labels with their IDs"""
    try:
        print("🔍 Fetching your Gmail labels...")
        print()

        service = get_gmail_service()
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        if not labels:
            print("No labels found.")
            return

        print("=" * 80)
        print(f"{'LABEL NAME':<40} {'LABEL ID':<40}")
        print("=" * 80)

        # Sort labels by name
        sorted_labels = sorted(labels, key=lambda x: x["name"].lower())

        for label in sorted_labels:
            name = label["name"]
            label_id = label["id"]

            # Highlight custom labels (not system labels)
            if label_id.startswith("Label_"):
                print(f"\033[1;32m{name:<40}\033[0m {label_id:<40}")  # Green for custom labels
            else:
                print(f"{name:<40} {label_id:<40}")

        print("=" * 80)
        print()
        print("✅ Found", len(labels), "labels")
        print()
        print("📝 Look for your job hunting label above (highlighted in green if custom)")
        print("   Copy the Label ID and add it to your .env file:")
        print()
        print("   GMAIL_JOBHUNT_LABEL_ID=Label_XXXXXXXXXXXXXXXXX")
        print()

    except Exception as e:
        print(f"❌ Error fetching labels: {e}")
        print()
        print("Troubleshooting:")
        print("1. Make sure json/credentials.json exists")
        print("2. If you see an authentication error, delete json/token.json and try again")
        print("3. Check that Gmail API is enabled in Google Cloud Console")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 80)
    print("  Gmail Label ID Finder")
    print("  GmailJobTracker Configuration Helper")
    print("=" * 80)
    print()

    list_labels()
