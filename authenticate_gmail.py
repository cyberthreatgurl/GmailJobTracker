#!/usr/bin/env python
"""
Gmail Authentication Helper

Run this script to authenticate with Gmail and generate token.pickle.
Works in any terminal environment - just copy/paste the URL if browser doesn't open.
"""

import os
import sys
from gmail_auth import get_gmail.._service


def get_token_path():
    """Return the path to the token file."""
    if os.path.exists("token.pickle"):
        return "token.pickle"
    return os.path.join("model", "token.pickle")


def main():
    print("\n🔐 Gmail Authentication Helper")
    print("=" * 70)

    service = get_gmail_service()

    # If authentication failed, check if token might be revoked and offer to delete it
    if not service:
        token_path = get_token_path()
        if os.path.exists(token_path):
            print(f"\n⚠️  Found existing token at: {token_path}")
            print("This token may be expired or revoked.")
            response = input("\nDelete old token and re-authenticate? [Y/n]: ").strip().lower()
            
            if response in ("", "y", "yes"):
                os.remove(token_path)
                print(f"✅ Deleted {token_path}")
                print("\nRetrying authentication...\n")
                print("=" * 70)
                
                # Retry authentication
                service = get_gmail_service()

    if service:
        print("\n✅ SUCCESS! Gmail authentication completed.")
        print("\nYour token.pickle file has been created with:")
        print("  ✓ Access token (expires in 1 hour)")
        print("  ✓ Refresh token (lasts forever, auto-refreshes access token)")
        print("\nYou can now:")
        print("  1. Run: python manage.py ingest_gmail --days-back 7")
        print(
            "  2. Copy token to server: scp model/token.pickle user@server:~/apps/GmailJobTracker/model/"
        )
        return 0
    else:
        print("\n❌ FAILED! Could not authenticate with Gmail.")
        print("\nTroubleshooting:")
        print("  1. Ensure json/credentials.json exists")
        print("  2. Check your internet connection")
        print("  3. Make sure you authorized the app in the browser")
        return 1


if __name__ == "__main__":
    sys.exit(main())
