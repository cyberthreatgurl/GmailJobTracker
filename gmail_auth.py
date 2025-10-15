from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import pickle

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

def get_gmail_service():
    creds = None
    token_path = os.path.join('model', 'token.pickle')
    credentials_path = os.path.join('json', 'credentials.json')

    try:
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
    except Exception as e:
        print(f"Error loading token file: {e}")

    try:
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
    except Exception as e:
        print(f"Error during credential flow: {e}")
        return None

    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Gmail service: {e}")
        return None