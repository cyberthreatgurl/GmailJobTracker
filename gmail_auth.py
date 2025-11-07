"""Gmail OAuth helper.

Provides `get_gmail_service()` which initializes an OAuth flow using
credentials from `json/credentials.json`, stores a refresh token under
`model/token.pickle`, and returns a Gmail API `Resource` for read-only access.
All credentials remain local to this machine.
"""

import os
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """Authorize and return a Gmail API service (read-only).

    Uses OAuth client secrets from `json/credentials.json` and persists the
    token under `model/token.pickle`. Returns a `googleapiclient.discovery.Resource`
    or None on failure.
    """
    creds = None
    token_path = os.path.join("model", "token.pickle")
    credentials_path = os.path.join("json", "credentials.json")

    try:
        if os.path.exists(token_path):
            with open(token_path, "rb") as token:
                creds = pickle.load(token)
    except Exception as e:
        print(f"Error loading token file: {e}")

    try:
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, "wb") as token:
                pickle.dump(creds, token)
    except Exception as e:
        print(f"Error during credential flow: {e}")
        return None

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Gmail service: {e}")
        return None
