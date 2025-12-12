"""Gmail OAuth helper.

Provides `get_gmail_service()` which initializes an OAuth flow using
credentials from `credentials.json`, stores a refresh token under
`token.pickle`, and returns a Gmail API `Resource` for read-only access.
All credentials remain local to this machine.
"""

import os
import pickle

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """Authorize and return a Gmail API service (read-only).

    Uses OAuth client secrets from `credentials.json` and persists the
    token in `token.pickle`. Automatically refreshes expired tokens.
    Returns a `googleapiclient.discovery.Resource` or None on failure.
    """
    creds = None
    
    # Support both old (json/) and new (root) paths for backward compatibility
    token_path = "token.pickle" if os.path.exists("token.pickle") else os.path.join("model", "token.pickle")
    credentials_path = "credentials.json" if os.path.exists("credentials.json") else os.path.join("json", "credentials.json")

    try:
        if os.path.exists(token_path):
            with open(token_path, "rb") as token:
                creds = pickle.load(token)
    except Exception as e:
        print(f"Error loading token file: {e}")

    try:
        # If credentials are invalid or expired, try to refresh them
        if creds and not creds.valid:
            if creds.expired and creds.refresh_token:
                print("Token expired, attempting refresh...")
                creds.refresh(Request())
                # Save the refreshed token
                with open(token_path, "wb") as token:
                    pickle.dump(creds, token)
                print("Token refreshed successfully")
            else:
                creds = None
        
        # If no valid credentials, need to authenticate (requires browser)
        if not creds:
            if not os.path.exists(credentials_path):
                print(f"Error: {credentials_path} not found. Please provide OAuth credentials.")
                return None
            print("\n" + "="*70)
            print("GMAIL AUTHENTICATION REQUIRED")
            print("="*70)
            print("Starting OAuth flow. A browser window should open automatically.")
            print("If the browser doesn't open, copy the URL from below.")
            print("="*70 + "\n")
            
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            # Request offline access to get a refresh token that never expires
            # open_browser=False to avoid issues in VS Code/SSH terminals
            creds = flow.run_local_server(
                port=0,
                access_type='offline',
                prompt='consent',  # Force consent screen to ensure refresh token is issued
                open_browser=False  # Print URL instead of trying to open browser
            )
            
            with open(token_path, "wb") as token:
                pickle.dump(creds, token)
            print("\n" + "="*70)
            print("✅ Authentication successful! Token saved with refresh token.")
            print(f"Token location: {os.path.abspath(token_path)}")
            print("="*70)
    except Exception as e:
        print(f"Error during credential flow: {e}")
        return None

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Gmail service: {e}")
        return None
