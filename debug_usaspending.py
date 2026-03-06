
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
    payload = {
        "filters": {
            "time_period": [
                {"start_date": "2025-01-01", "end_date": date.today().isoformat()}
            ],
            "award_type_codes": ["A", "B", "C", "D"],
            "keyword": "Boeing",
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Place of Performance Country Name",
            "Place of Performance City Name",
            "Place of Performance County Name",
            "Place of Performance State Code",
            "Recipient Location City Name",
            "Recipient Location State Code",
            "Recipient Location Country Name", # Added for check
        ],
        "page": 1,
        "limit": 1,
        "sort": "Base Obligation Date",
        "order": "desc",
    }

    url = f"{USASPENDING_API_BASE}{SEARCH_ENDPOINT}"
    print(f"Requesting: {url}")
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        
        results = data.get("results", [])
        if results:
            print("Successfully fetched a contract.")
            print(json.dumps(results[0], indent=2))
        else:
            print("No results found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fetch_sample_contract()
