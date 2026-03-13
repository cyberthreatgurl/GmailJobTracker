import os
import requests
import logging
import time
from django.conf import settings
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SamGovClient:
    """
    Client for SAM.gov Opportunities API (search).
    Docs: https://open.gsa.gov/api/get-opportunities-public-api/
    """
    BASE_URL = "https://api.sam.gov/opportunities/v2/search"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("SAM_GOV_API_KEY")
        if not self.api_key:
            logger.warning("SAM_GOV_API_KEY not found in environment settings.")

    def search_opportunities(self, params=None):
        """
        Search for opportunities.
        
        Args:
            params (dict): Search parameters. Common params:
                - postedFrom: MM/DD/YYYY
                - postedTo: MM/DD/YYYY
                - limit: int
                - offset: int
                - sort: str (e.g. "-postedDate")
                - ptype: str (e.g. "o,k" for original, combined synopsis/solicitation)
                
        Returns:
            dict: JSON response from API.
        """
        if not self.api_key:
             return {"error": "API Key not configured"}

        default_params = {
            "api_key": self.api_key,
            "limit": 10,
            "postedFrom": (datetime.now() - timedelta(days=30)).strftime("%m/%d/%Y"),
            "postedTo": datetime.now().strftime("%m/%d/%Y"),
        }
        
        if params:
            default_params.update(params)

        try:
            response = requests.get(self.BASE_URL, params=default_params)
            
            # Manual retry on 429 (Too Many Requests) with Retry-After support
            if response.status_code == 429:
                wait_time = 2
                retry_header = response.headers.get("Retry-After")
                
                if retry_header:
                    try:
                        wait_time = int(retry_header)
                    except ValueError:
                        # Could be HTTP-date format, just default to 5s if parsing fails for now
                        wait_time = 5
                
                logger.warning(f"SAM.gov returned 429 Rate Limit Exceeded. Backing off for {wait_time} seconds...")
                time.sleep(wait_time)
                response = requests.get(self.BASE_URL, params=default_params)

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 429:
                 retry_after = e.response.headers.get("Retry-After", "a short while")
                 return {"error": f"Rate limit exceeded (429). Please wait {retry_after} seconds and try again."}
            logger.error(f"SAM.gov API HTTP Error: {e}")
            return {"error": str(e), "details": response.text if 'response' in locals() else ""}
        except Exception as e:
            logger.error(f"SAM.gov API Error: {e}")
            return {"error": str(e)}

    def fetch_description(self, notice_id):
        """
        Directly fetch description HTML for a given notice/solicitation ID.

        Uses the SAM.gov v1 notice description endpoint, which accepts the same
        identifier that appears in https://sam.gov/opp/{noticeId}/view URLs.
        Returns the raw HTML string on success, or None on failure.
        """
        if not self.api_key or not notice_id:
            return None
        try:
            resp = requests.get(
                "https://api.sam.gov/prod/opportunities/v1/noticedesc",
                params={"noticeid": notice_id, "api_key": self.api_key},
                timeout=15,
            )
            resp.raise_for_status()
            text = resp.text.strip()
            return text or None
        except Exception as e:
            logger.error(f"SAM.gov description fetch error for notice '{notice_id}': {e}")
            return None
