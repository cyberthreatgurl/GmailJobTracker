
import logging
import requests
import json
from datetime import date

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USASPENDING_API_BASE = "https://api.usaspending.gov"
SEARCH_ENDPOINT = "/api/v2/search/spending_by_award/"

def fetch_sample_contract():
    print(f"Fetching from {USASPENDING_API_BASE}")
    
    # Payload similar to service, simplified
    payload = {
        "filters": {
            "time_period": [
                {"start_date": "2024-01-01", "end_date": "2025-01-01"} 
            ],
            "award_type_codes": ["A", "B", "C", "D"],
            "keyword": "Lockheed Martin"
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Base Obligation Date",
            "Award Amount",
            "Place of Performance Country Code",
            "Place of Performance State Code",
            "Place of Performance City Code",
            "Place of Performance County Code",
            "Recipient Location Country Code",
            "Recipient Location State Code",
            "Recipient Location City Code",
            "Recipient Location County Code",
        ],
        "page": 1,
        "limit": 5,
        "sort": "Base Obligation Date",
        "order": "desc",
    }
    
    url = f"{USASPENDING_API_BASE}{SEARCH_ENDPOINT}"
    
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        # response.raise_for_status() # Commented out to see error body
        
        try:
            data = response.json()
        except:
            print(f"Response (not JSON): {response.text}")
            return

        if response.status_code != 200:
             print(f"API Error ({response.status_code}): {json.dumps(data, indent=2)}")
             return
        
        results = data.get("results", [])
        if results:
            print(f"Found {len(results)} contracts.")
            print("First contract sample:")
            print(json.dumps(results[0], indent=2))
        else:
            print("No contracts found.")
            # Print full response for diagnosis
            print(json.dumps(data, indent=2))
            
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    fetch_sample_contract()
