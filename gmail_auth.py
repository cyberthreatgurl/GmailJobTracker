"""Gmail OAuth helper.

Provides `get_gmail_service()` which initializes an OAuth flow using
credentials from `credentials.json`, stores a refresh token under
`token.pickle`, and returns a Gmail API `Resource` for read-only access.
All credentials remain local to this machine.
"""

import os
import pickle
import json
from urllib.parse import urlparse

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _get_oauth_port() -> int:
    """Return the localhost port for the OAuth callback server.

    Defaults to ``8080`` to match the common Google OAuth loopback setup.
    Set ``GMAIL_OAUTH_PORT`` to force a different port if needed.
    """
    raw_port = os.environ.get("GMAIL_OAUTH_PORT", "8080").strip()
    try:
        port = int(raw_port)
    except ValueError:
        print(f"Invalid GMAIL_OAUTH_PORT '{raw_port}', falling back to 8080.")
        return 8080
    return port if port > 0 else 8080


def _load_client_config(credentials_path: str) -> tuple[str, dict] | tuple[None, None]:
    """Return the OAuth client type and config from a client secrets file."""
    try:
        with open(credentials_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading OAuth client config: {exc}")
        return None, None

    if "installed" in config:
        return "installed", config["installed"]
    if "web" in config:
        return "web", config["web"]
    print("Error: credentials.json must contain either an 'installed' or 'web' client config.")
    return None, None


def _resolve_oauth_port(client_type: str, client_config: dict) -> int | None:
    """Choose a callback port that matches the OAuth client configuration."""
    requested_port = _get_oauth_port()
    redirect_uris = client_config.get("redirect_uris", []) or []

    if client_type == "installed":
        return requested_port

    localhost_redirects = []
    for uri in redirect_uris:
        parsed = urlparse(uri)
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            localhost_redirects.append(parsed)

    if localhost_redirects:
        for parsed in localhost_redirects:
            if (parsed.port or 80) == requested_port:
                return requested_port

    print("OAuth client misconfiguration detected.")
    print("Your credentials.json contains a 'web' client without an authorized localhost redirect URI.")
    print("Fix one of these and retry:")
    print("  1. Create a Desktop app OAuth client in Google Cloud and replace credentials.json")
    print(
        f"  2. Or add an Authorized redirect URI like http://localhost:{requested_port}/ "
        "to the existing Web client"
    )
    print(
        f"     and then run the command with GMAIL_OAUTH_PORT={requested_port}."
    )
    return None


def get_gmail_service():
    """Authorize and return a Gmail API service (read-only).

    Uses OAuth client secrets from `credentials.json` and persists the
    token in `token.pickle`. Automatically refreshes expired tokens.
    Returns a `googleapiclient.discovery.Resource` or None on failure.
    """
    creds = None

    token_path = "token.pickle"
    credentials_path = "credentials.json"

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
                print(
                    f"Error: {credentials_path} not found. Please provide OAuth credentials."
                )
                return None
            client_type, client_config = _load_client_config(credentials_path)
            if not client_type or client_config is None:
                return None
            print("\n" + "=" * 70)
            print("GMAIL AUTHENTICATION REQUIRED")
            print("=" * 70)
            print("Starting OAuth flow. A browser window should open automatically.")
            print("If the browser doesn't open, copy the URL from below.")
            print("=" * 70 + "\n")

            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            # Request offline access to get a refresh token that never expires
            # open_browser=False to avoid issues in VS Code/SSH terminals
            oauth_port = _resolve_oauth_port(client_type, client_config)
            if oauth_port is None:
                return None
            if oauth_port == 0:
                print("Using an automatically selected localhost callback port.")
            else:
                print(f"Using localhost callback port {oauth_port}.")
            creds = flow.run_local_server(
                port=oauth_port,
                access_type="offline",
                prompt="consent",  # Force consent screen to ensure refresh token is issued
                open_browser=False,  # Print URL instead of trying to open browser
            )

            with open(token_path, "wb") as token:
                pickle.dump(creds, token)
            print("\n" + "=" * 70)
            print("✅ Authentication successful! Token saved with refresh token.")
            print(f"Token location: {os.path.abspath(token_path)}")
            print("=" * 70)
    except Exception as e:
        print(f"Error during credential flow: {e}")
        return None

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        print(f"Error building Gmail service: {e}")
        return None
