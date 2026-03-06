import os
import sys
import json
import requests
import django
from datetime import date
from pprint import pprint

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.services.usaspending_service import USASpendingService

# Custom recursive printer
def print_keys_recursive(d, indent=0):
    prefix = "  " * indent
    if isinstance(d, dict):
        for k in sorted(d.keys()):
            v = d[k]
            if isinstance(v, (dict, list)):
                if v:
                    print(f"{prefix}{k}: <{type(v).__name__} with {len(v)} items>")
                    # Only recurse if it's not huge or too deep
                    if indent < 2:
                        print_keys_recursive(v, indent + 1)
                else:
                    print(f"{prefix}{k}: <empty {type(v).__name__}>")
            else:
                val = str(v)
                if len(val) > 100:
                    val = val[:100] + "..."
                # Clean up newlines for display
                val = val.replace("\n", " ")
                print(f"{prefix}{k}: {val}")
    elif isinstance(d, list):
        if d:
            print(f"{prefix}[List of {len(d)} items]")
            if indent < 2:
                # Print schema of first item only
                print(f"{prefix}  Item 0:")
                print_keys_recursive(d[0], indent + 1)
        else:
            print(f"{prefix}[]")

def inspect_api_fields():
    print("Initializing Service...")
    
    # 1. Use the service to get a contract ID
    try:
        service = USASpendingService(start_date="2025-01-01")
        
        print("1. Fetching 1 contract using USASpendingService...")
        # Access internal method to get raw API response for 1 item
        raw_contracts = service._fetch_contracts_from_api(limit=1)
        
        if not raw_contracts:
            print("❌ Service returned no contracts. Ensure data exists for this date range.")
            return

        item = raw_contracts[0]
        internal_id = item.get("generated_internal_id")
        display_id = item.get("Award ID", "Unknown")
        
        if not internal_id:
             print("❌ No 'generated_internal_id' found in search result. Keys available:")
             pprint(list(item.keys()))
             return
             
        print(f"   ✅ Found Contract: {display_id} (Internal ID: {internal_id})")
        
        # 2. Query the Award Detail endpoint
        # Endpoint: /api/v2/awards/{generated_internal_id}/
        detail_url = f"https://api.usaspending.gov/api/v2/awards/{internal_id}/"
        
        print(f"\n2. Fetching FULL details from {detail_url}...")
        
        detail_resp = requests.get(detail_url, timeout=15)
        detail_resp.raise_for_status()
        full_data = detail_resp.json()
        
        print(f"\n✅ FULL DATA AVAILABLE FOR CONTRACT {display_id}")
        print("=" * 80)
        print_keys_recursive(full_data)
        print("=" * 80)
        
        # Save to JSON file for easier inspection
        output_file = "usaspending_sample_contract.json"
        with open(output_file, "w") as f:
            json.dump(full_data, f, indent=2)
            
        print(f"\n✅ Saved full contract data to {output_file} (Open this file to browse the data structure)")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    inspect_api_fields()
