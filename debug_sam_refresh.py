
import os
import django
import json
from dotenv import load_dotenv

# Load env manually just in case
load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.services.sam_gov_service import SamGovClient

def debug_fetch():
    client = SamGovClient()
    solicitation = "M6785426I0097"
    print(f"Searching for solicitation: {solicitation}")
    
    # Try search by solicitationNumber
    params = {"solicitationNumber": solicitation, "limit": 1}
    data = client.search_opportunities(params=params)
    
    if "opportunitiesData" in data and data["opportunitiesData"]:
        opp = data["opportunitiesData"][0]
        print(f"Found! Notice ID: {opp.get('noticeId')}")
        print(f"UI Link from API: {opp.get('uiLink')}")
        print(f"Constructed Link: https://sam.gov/opp/{opp.get('noticeId')}/view")
    else:
        print("Not found by solicitation number.")
        print(json.dumps(data, indent=2))

if __name__ == "__main__":
    debug_fetch()
