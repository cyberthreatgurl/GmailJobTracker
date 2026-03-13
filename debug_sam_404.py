
import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("SAM_GOV_API_KEY")

def debug_contract_search():
    base_url = "https://api.sam.gov/opportunities/v2/search"
    target_id = "1333HK26C00000007"
    
    # Range covering "today" (2026-03-11) based on DB finding
    posted_from = "03/10/2026"
    posted_to = "03/12/2026"
    
    print(f"--- Debugging {target_id} ---")
    
    # 1. Try search as Solicitation Number
    print("\n1. Searching as solicitationNumber...")
    params = {
        "api_key": api_key,
        "limit": 1,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "solicitationNumber": target_id
    }
    try:
        r = requests.get(base_url, params=params)
        print(f"Status: {r.status_code}")
        data = r.json()
        if data.get("opportunitiesData"):
            print("FOUND! It is a solicitationNumber.")
            print(json.dumps(data["opportunitiesData"][0], indent=2))
        else:
            print("NOT FOUND as solicitationNumber.")
            if "error" in data: print(data)
    except Exception as e:
        print(e)
        
    # 2. Try search as Keyword (broad search)
    # Note: SAM API key param name for keyword is usually not documented clearly as 'keyword' in v2 search 
    # but let's try 'title' or just rely on 'solicitationNumber' being the wrong field.
    # Actually, v2 search doesn't have a generic 'keyword' field easily exposed in all docs, 
    # but let's try noticeId if documented. 
    # Let's try `noticeId` validation.
    
    print("\n2. Searching as noticeId...")
    params = {
        "api_key": api_key,
        "limit": 1,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "noticeId": target_id
    }
    try:
        r = requests.get(base_url, params=params)
        print(f"Status: {r.status_code}")
        data = r.json()
        if data.get("opportunitiesData"):
            print("FOUND! It is a noticeId.")
            print(json.dumps(data["opportunitiesData"][0], indent=2))
        else:
            print("NOT FOUND as noticeId.")
            
    except Exception as e:
        print(e)

if __name__ == "__main__":
    debug_contract_search()
