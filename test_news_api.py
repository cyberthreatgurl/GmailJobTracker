import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("NEWS_API_KEY")

if not api_key:
    print("NO API KEY")
    sys.exit(1)

url = "https://newsapi.org/v2/everything"
params = {
    "q": "apple",
    "sortBy": "publishedAt",
    "language": "en",
    "apiKey": api_key,
    "pageSize": 5
}

print("Testing without 'from':")
resp = requests.get(url, params=params)
print(resp.status_code)
if resp.status_code != 200:
    print(resp.text)

params["from"] = "2026-02-13"  # Try 27 days
print("\nTesting with 'from':")
resp = requests.get(url, params=params)
print(resp.status_code)
if resp.status_code != 200:
    print(resp.text)
