import requests
import json

USASPENDING_API_BASE = "https://api.usaspending.gov"
SEARCH_ENDPOINT = "/api/v2/search/spending_by_award/"

def main():
    url = f"{USASPENDING_API_BASE}{SEARCH_ENDPOINT}"
    
    # Old fields
    fields = [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Base Obligation Date",
        "Description",
        "Place of Performance Country Name",
        "Place of Performance City Name",
        "Place of Performance County Name",
        "Place of Performance State Code",
        "Recipient Location City Name",
        "Recipient Location State Code",
        "generated_internal_id",
        
        # New suggested fields
        "Primary Place of Performance",
        "Recipient Location"
    ]
    
    payload = {
        "filters": {
            "time_period": [
                {"start_date": "2024-01-01", "end_date": "2024-01-31"}
            ],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "fields": fields,
        "limit": 1
    }
    
    print(f"Calling {url}...")
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        results = data.get("results", [])
        if not results:
            print("No results found.")
            return

        item = results[0]
        print("\n--- Response for one award ---")
        print(json.dumps(item, indent=2))
        
        print("\n--- Field Analysis ---")
        for field in fields:
            value = item.get(field)
            status = "PRESENT" if value is not None else "NULL/MISSING"
            print(f"{field}: {status} ({value})")

    except requests.exceptions.RequestException as e:
        print(f"Error calling API: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"Response content: {e.response.text}")

if __name__ == "__main__":
    main()
