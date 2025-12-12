#!/usr/bin/env python
"""
Gmail Authentication Helper

Run this script to authenticate with Gmail and generate token.pickle.
Works in any terminal environment - just copy/paste the URL if browser doesn't open.
"""

import sys
from gmail_auth import get_gmail_service

def main():
    print("\n🔐 Gmail Authentication Helper")
    print("=" * 70)
    
    service = get_gmail_service()
    
    if service:
        print("\n✅ SUCCESS! Gmail authentication completed.")
        print("\nYour token.pickle file has been created with:")
        print("  ✓ Access token (expires in 1 hour)")
        print("  ✓ Refresh token (lasts forever, auto-refreshes access token)")
        print("\nYou can now:")
        print("  1. Run: python manage.py ingest_gmail --days-back 7")
        print("  2. Copy token to server: scp model/token.pickle user@server:~/apps/GmailJobTracker/model/")
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
