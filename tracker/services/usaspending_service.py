"""
USASpending.gov API Integration Service

Fetches federal contract awards from USASpending.gov API and creates DefenseContract
records. This service complements the existing war.gov scraper to provide comprehensive
government contract tracking across all federal agencies.

API Documentation: https://api.usaspending.gov/docs/endpoints

Usage:
    from tracker.services.usaspending_service import USASpendingService

    service = USASpendingService(start_date="2025-10-01")
    stats = service.fetch_and_save_contracts(limit=100)
    # Returns: {'created': 95, 'skipped': 5, 'errors': 0}
"""

import logging
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

import requests
from django.db import IntegrityError
from django.utils.timezone import now
from thefuzz import fuzz

from tracker.models import Company, CompanyAlias, DefenseContract
from tracker.utils.company_normalization import normalize_company_name

logger = logging.getLogger(__name__)

# USASpending API configuration
USASPENDING_API_BASE = "https://api.usaspending.gov"
SEARCH_ENDPOINT = "/api/v2/search/spending_by_award/"

# Rate limiting: 1 second between requests (conservative, no official limit documented)
REQUEST_DELAY_SECONDS = 1.0

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0

# Company matching threshold (fuzzy string match)
COMPANY_MATCH_THRESHOLD = 85

# Valid agency codes for whitelist validation
VALID_AGENCY_CODES = {
    "DOD", "DHS", "DOE", "DOJ", "DOT", "HHS", "VA", "DOS", "DOI", "DOC",
    "DOL", "USDA", "ED", "HUD", "TREAS", "NASA", "EPA", "GSA", "NSF",
    "SBA", "SSA", "USAID", "OPM", "NRC", "FCC", "SEC", "CFTC", "FTC",
}


class USASpendingAPIError(Exception):
    """Raised when USASpending API returns an error or unexpected response."""


class USASpendingService:
    """
    Service class for fetching and processing federal contract awards from
    USASpending.gov API.

    Attributes:
        start_date: ISO format date string (YYYY-MM-DD) for filtering contracts
        end_date: ISO format date string, defaults to today
        timeout: HTTP request timeout in seconds
    """

    def __init__(
        self,
        start_date: str = "2025-01-01",
        end_date: Optional[str] = None,
        timeout: int = 10,
    ):
        """
        Initialize USASpending service with date range.

        Args:
            start_date: Start date in YYYY-MM-DD format (FY2025 Q1 start)
            end_date: End date in YYYY-MM-DD format (defaults to today)
            timeout: HTTP request timeout in seconds

        Raises:
            ValueError: If dates are invalid or start_date is before 2025-10-01
        """
        self.timeout = timeout

        # Validate and store start date
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(
                f"Invalid start_date format: {start_date}. Expected YYYY-MM-DD"
            ) from exc

        min_date = date(2025, 1, 1)
        if start_dt < min_date:
            raise ValueError(
                f"start_date {start_date} is before minimum date 2025-01-01"
            )

        self.start_date = start_date

        # Set end date to today if not provided
        if end_date is None:
            self.end_date = date.today().isoformat()
        else:
            try:
                datetime.strptime(end_date, "%Y-%m-%d")
                self.end_date = end_date
            except ValueError as exc:
                raise ValueError(
                    f"Invalid end_date format: {end_date}. Expected YYYY-MM-DD"
                ) from exc

        logger.info(
            "Initialized USASpendingService with date range: %s to %s",
            self.start_date,
            self.end_date,
        )

    def fetch_contracts_for_company(
        self,
        company_name: str,
        start_date: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Fetch contracts for a specific company (last 12 months by default).

        Args:
            company_name: The name of the company to search for.
            start_date: Start date for search (YYYY-MM-DD). Defaults to 365 days ago.

        Returns:
            Dict with keys: created, updated, errors
        """
        if not start_date:
            start_date = (date.today() - timedelta(days=365)).isoformat()
        
        # Ensure we have a valid end date for the query (today)
        self.end_date = date.today().isoformat()
        self.start_date = start_date # Override service instance start date
        
        # Normalize company name for API search
        norm_name = normalize_company_name(company_name)
        if not norm_name:
            logger.warning("Company name '%s' normalized to empty string, using raw", company_name)
            norm_name = company_name

        # Collect search keywords: Canonical name + Aliases
        search_terms = {norm_name} # Use set to dedup
        
        # Get aliases for this company
        # CompanyAlias.company is a string, not a FK
        aliases = CompanyAlias.objects.filter(company__iexact=company_name).values_list('alias', flat=True)
        for alias in aliases:
            norm_alias = normalize_company_name(alias)
            if norm_alias:
                search_terms.add(norm_alias)
        
        # Convert back to list for iteration
        keywords_list = list(search_terms)

        logger.info("Fetching contracts for company '%s' using terms: %s since %s", company_name, keywords_list, start_date)

        # Force a reasonable limit for company specific fetch
        limit = 100 
        
        created = 0
        updated = 0
        errors = 0
        
        # Determine target company object
        target_company = Company.objects.filter(name__iexact=company_name).first()

        # Iterate over each search term (name + aliases)
        for term in keywords_list:
            # Use existing logic but pass single keyword as list
            raw_contracts = self._fetch_contracts_from_api(limit, keywords=[term])
            
            if not raw_contracts:
                logger.debug("No contracts found for term '%s'", term)
                continue

            for raw in raw_contracts:
                try:
                    parsed = self._parse_contract(raw)
                    
                    # Force the link to the target company regardless of internal matching logic
                    if target_company:
                        parsed["company"] = target_company
    
                    saved, is_new = self._save_contract(parsed, overwrite=True)
                    if saved:
                        if is_new:
                            created += 1
                        else:
                            updated += 1
                    else:
                        # Should not happen with overwrite=True unless error
                        pass
                except Exception as e:
                    logger.error("Error processing contract for %s: %s", term, e)
                    errors += 1
                
        return {"created": created, "updated": updated, "errors": errors}

    def fetch_and_save_contracts(
        self,
        limit: int = 500,
        agency_codes: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """
        Fetch contracts from USASpending API and save to database.

        Args:
            limit: Maximum number of contracts to fetch (capped at 1000)
            agency_codes: List of agency codes to filter by (e.g., ['DOD', 'DHS'])

        Returns:
            Dict with keys: created, skipped, errors

        Raises:
            USASpendingAPIError: If API request fails after retries
        """
        # Validate and cap limit
        if limit < 1:
            raise ValueError("limit must be at least 1")
        limit = min(limit, 1000)

        # Validate agency codes if provided
        if agency_codes:
            invalid = set(agency_codes) - VALID_AGENCY_CODES
            if invalid:
                logger.warning(
                    "Invalid agency codes will be ignored: %s", ", ".join(invalid)
                )
                agency_codes = [c for c in agency_codes if c in VALID_AGENCY_CODES]

        # Fetch raw contract data from API
        logger.info("Fetching up to %d contracts from USASpending API", limit)
        raw_contracts = self._fetch_contracts_from_api(limit, agency_codes)

        if not raw_contracts:
            logger.warning("No contracts returned from API")
            return {"created": 0, "skipped": 0, "errors": 0}

        logger.info("Fetched %d raw contracts, processing...", len(raw_contracts))

        # Process and save contracts
        created = 0
        skipped = 0
        errors = 0

        for raw_contract in raw_contracts:
            try:
                parsed = self._parse_contract(raw_contract)
                if self._save_contract(parsed):
                    created += 1
                else:
                    skipped += 1
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error processing contract: %s", exc, exc_info=True)
                errors += 1

        logger.info(
            "Completed: %d created, %d skipped, %d errors", created, skipped, errors
        )
        return {"created": created, "skipped": skipped, "errors": errors}

    def _fetch_contracts_from_api(
        self,
        limit: int,
        agency_codes: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Fetch contracts from API."""
        contracts = []
        page = 1
        per_page = 50  # Lower limit slightly for keyword searches

        # If keyword search, we likely won't get huge pages, but let's be safe
        
        while len(contracts) < limit:
            # Build request payload
            payload = self._build_api_payload(page, per_page, agency_codes, keywords=keywords)

            # Make request with retries
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    response = self._make_api_request(payload)
                    break 
                except: # ... (existing retry logic handled in original code block)
                    if attempt == MAX_RETRIES:
                        raise
                    time.sleep(1)

            # Parse results
            results = response.get("results", [])
            if not results:
                break
            
            contracts.extend(results)
            if len(results) < per_page:
                break
            page += 1
            time.sleep(1)

        return contracts[:limit]

    def _build_api_payload(
        self,
        page: int,
        per_page: int,
        agency_codes: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> Dict:
        """
        Build API request payload.

        Args:
            keywords: List of search terms. USASpending supports recipient_search_text
                      or bare keywords.
        """
        payload = {
            "filters": {
                "time_period": [
                    {"start_date": self.start_date, "end_date": self.end_date}
                ],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": [
                "Award ID",
                "Recipient Name",
                "Award Amount",
                "Awarding Agency",
                "Awarding Sub Agency",
                "Base Obligation Date",
                "Description",
                "Primary Place of Performance",
                "Recipient Location",
                "generated_internal_id",
                "Highly Compensated Officer 1 Name",
                "Highly Compensated Officer 1 Amount",
                "Highly Compensated Officer 2 Name",
                "Highly Compensated Officer 2 Amount",
                "Highly Compensated Officer 3 Name",
                "Highly Compensated Officer 3 Amount",
                "Highly Compensated Officer 4 Name",
                "Highly Compensated Officer 4 Amount",
                "Highly Compensated Officer 5 Name",
                "Highly Compensated Officer 5 Amount",
            ],
            "page": page,
            "limit": per_page,
            "sort": "Base Obligation Date",
            "order": "desc",
        }

        if keywords:
            # Use general keyword search (instead of recipient_search_text) to match
            # both recipient names AND contract descriptions (e.g. for products/resellers).
            # The API 'keyword' filter takes a single string.
            search_term = keywords[0] if isinstance(keywords, list) and keywords else str(keywords)
            payload["filters"]["keyword"] = search_term

        if agency_codes:
            payload["filters"]["agencies"] = [
                {"type": "awarding", "tier": "toptier", "name": code}
                for code in agency_codes
            ]

        return payload

    def _make_api_request(self, payload: Dict) -> Dict:
        """
        Make POST request to USASpending API.

        Args:
            payload: Request payload dict

        Returns:
            Response JSON as dict

        Raises:
            USASpendingAPIError: If request fails or response invalid
        """
        url = f"{USASPENDING_API_BASE}{SEARCH_ENDPOINT}"

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
                allow_redirects=False,  # SSRF protection
            )
            response.raise_for_status()

            # Validate content type
            content_type = response.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                raise USASpendingAPIError(
                    f"Unexpected content-type: {content_type}. Expected application/json"
                )

            return response.json()

        except requests.exceptions.Timeout as exc:
            raise USASpendingAPIError(f"API request timed out after {self.timeout}s") from exc
        except requests.exceptions.RequestException as exc:
            raise USASpendingAPIError(f"API request failed: {exc}") from exc
        except ValueError as exc:
            raise USASpendingAPIError(f"Invalid JSON response: {exc}") from exc

    def _parse_contract(self, raw_data: Dict) -> Dict:
        """
        Parse raw API response into DefenseContract field mapping.

        Args:
            raw_data: Raw contract dict from API response

        Returns:
            Dict with fields ready for DefenseContract.objects.create()

        Raises:
            ValueError: If required fields are missing
        """
        # Validate required fields
        award_id = raw_data.get("Award ID", "").strip()
        generated_internal_id = raw_data.get("generated_internal_id", "").strip()
        recipient_name = raw_data.get("Recipient Name", "").strip()

        if not award_id:
            raise ValueError("Missing required field: Award ID")
        if not recipient_name:
            raise ValueError("Missing required field: Recipient Name")
        
        # Build source URL using generated_internal_id if available, else fallback to award_id
        if generated_internal_id:
            source_url = f"https://www.usaspending.gov/award/{generated_internal_id}"
        else:
            source_url = f"https://www.usaspending.gov/award/{award_id}"
            logger.warning("No generated_internal_id for award %s, using award_id in URL", award_id)

        # Parse award amount
        amount = None
        amount_raw = raw_data.get("Award Amount")
        if amount_raw:
            try:
                amount = Decimal(str(amount_raw))
            except (InvalidOperation, ValueError, TypeError):
                logger.warning("Invalid amount for award %s: %s", award_id, amount_raw)

        # Parse award date
        article_date = None
        date_raw = raw_data.get("Base Obligation Date", "").strip()
        if date_raw:
            try:
                article_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except ValueError:
                logger.warning("Invalid date format for award %s: %s", award_id, date_raw)
                article_date = date.today()
        else:
            article_date = date.today()

        # Extract other fields with defaults (handle None values)
        awarding_agency = (raw_data.get("Awarding Agency") or "").strip()
        awarding_sub_agency = (raw_data.get("Awarding Sub Agency") or "").strip()
        description = (raw_data.get("Description") or "").strip()

        # Extract Place of Performance (nested object)
        pop_data = raw_data.get("Primary Place of Performance") or {}
        work_country = (pop_data.get("country_name") or "").strip()
        work_city = (pop_data.get("city_name") or "").strip()
        work_county = (pop_data.get("county_name") or "").strip()
        work_state = (pop_data.get("state_code") or "").strip()

        # Extract Recipient Location (nested object)
        recipient_data = raw_data.get("Recipient Location") or {}
        recipient_city = (recipient_data.get("city_name") or "").strip()
        recipient_state = (recipient_data.get("state_code") or "").strip()

        # Extract officer names
        officer_1_name = (raw_data.get("Highly Compensated Officer 1 Name") or "").strip()
        officer_2_name = (raw_data.get("Highly Compensated Officer 2 Name") or "").strip()
        officer_3_name = (raw_data.get("Highly Compensated Officer 3 Name") or "").strip()
        officer_4_name = (raw_data.get("Highly Compensated Officer 4 Name") or "").strip()
        officer_5_name = (raw_data.get("Highly Compensated Officer 5 Name") or "").strip()

        # Helper for amount parsing
        def parse_amount(val):
            if val:
                try:
                    return Decimal(str(val))
                except (InvalidOperation, ValueError, TypeError):
                    return None
            return None

        off_1_amt = parse_amount(raw_data.get("Highly Compensated Officer 1 Amount"))
        off_2_amt = parse_amount(raw_data.get("Highly Compensated Officer 2 Amount"))
        off_3_amt = parse_amount(raw_data.get("Highly Compensated Officer 3 Amount"))
        off_4_amt = parse_amount(raw_data.get("Highly Compensated Officer 4 Amount"))
        off_5_amt = parse_amount(raw_data.get("Highly Compensated Officer 5 Amount"))

        # Build work location string (where work is performed)
        work_location = ""
        # Prefer "City, St" format
        if work_city and work_state:
            work_location = f"{work_city}, {work_state}"
        elif work_city:
            work_location = work_city
        elif work_state:
            work_location = work_state

        # Append country if not US
        if work_country and work_country.upper() not in ["USA", "UNITED STATES"]:
            if work_location:
                 work_location += f", {work_country}"
            else:
                 work_location = work_country

        # Build company location string (recipient's address)
        company_location = ""
        if recipient_city and recipient_state:
            company_location = f"{recipient_city}, {recipient_state}"
        elif recipient_city:
            company_location = recipient_city
        elif recipient_state:
            company_location = recipient_state

        # Attempt company matching
        company = self._match_company(recipient_name)

        return {
            "data_source": "usaspending",
            "award_id": award_id,
            "generated_internal_id": generated_internal_id,
            "source_url": source_url,
            "article_date": article_date,
            "company_name_raw": recipient_name,
            "company": company,
            "company_location": company_location,
            "awarding_agency": awarding_agency,
            "awarding_sub_agency": awarding_sub_agency,
            "branch": "other",  # USASpending doesn't use military branch classification
            "amount": amount,
            "description": description,
            "work_location": work_location,
            "place_of_performance_state": work_state,
            "primary_place_of_performance_country_name": work_country,
            "primary_place_of_performance_city_name": work_city,
            "primary_place_of_performance_county_name": work_county,
            "highly_compensated_officer_1_name": officer_1_name,
            "highly_compensated_officer_1_amount": off_1_amt,
            "highly_compensated_officer_2_name": officer_2_name,
            "highly_compensated_officer_2_amount": off_2_amt,
            "highly_compensated_officer_3_name": officer_3_name,
            "highly_compensated_officer_3_amount": off_3_amt,
            "highly_compensated_officer_4_name": officer_4_name,
            "highly_compensated_officer_4_amount": off_4_amt,
            "highly_compensated_officer_5_name": officer_5_name,
            "highly_compensated_officer_5_amount": off_5_amt,
            "contract_number": "",  # Not provided by USASpending search endpoint
            "raw_text": str(raw_data),  # Store full JSON for debugging
        }

    def _match_company(self, recipient_name: str) -> Optional[Company]:
        """
        Attempt to match USASpending recipient name to existing Company record.

        Uses two strategies:
        1. Exact case-insensitive name match
        2. Fuzzy string matching (85%+ similarity)

        Args:
            recipient_name: Company name from USASpending

        Returns:
            Company instance if match found, else None
        """
        if not recipient_name:
            return None

        # Strategy 1: Exact match (case-insensitive)
        exact_match = Company.objects.filter(name__iexact=recipient_name).first()
        if exact_match:
            logger.debug("Exact company match: %s → %s", recipient_name, exact_match.name)
            return exact_match

        # Strategy 1b: Exact alias match (case-insensitive)
        # Note: CompanyAlias.company is a string, so we must then find the Company object
        alias_match = CompanyAlias.objects.filter(alias__iexact=recipient_name).first()
        if alias_match:
            # Resolve alias string to Company object
            canonical_company = Company.objects.filter(name__iexact=alias_match.company).first()
            if canonical_company:
                logger.debug("Exact alias match: %s → %s (via alias %s)", 
                             recipient_name, canonical_company.name, alias_match.alias)
                return canonical_company

        # Strategy 2: Fuzzy matching
        # Limit search to companies with similar first letter for performance
        first_char = recipient_name[0].upper()
        candidates = Company.objects.filter(name__istartswith=first_char)

        best_match = None
        best_score = 0

        for company in candidates:
            score = fuzz.ratio(recipient_name.lower(), company.name.lower())
            if score > best_score:
                best_score = score
                best_match = company

        # Also check aliases for fuzzy match if primary check not perfect
        if best_score < 100:
            alias_candidates = CompanyAlias.objects.filter(alias__istartswith=first_char)
            for alias_obj in alias_candidates:
                score = fuzz.ratio(recipient_name.lower(), alias_obj.alias.lower())
                
                # Give alias matches slightly lower priority if score is tied? 
                # Or just update if strictly better?
                if score > best_score:
                    # Resolve to Company object
                    canonical_company = Company.objects.filter(name__iexact=alias_obj.company).first()
                    if canonical_company:
                        best_score = score
                        best_match = canonical_company
                    
        if best_score >= COMPANY_MATCH_THRESHOLD:
            logger.debug(
                "Fuzzy company match (%d%%): %s → %s",
                best_score,
                recipient_name,
                best_match.name,
            )
            return best_match

        logger.debug("No company match found for: %s", recipient_name)
        return None

    @staticmethod
    def check_award_published(generated_internal_id: str, timeout: int = 5) -> bool:
        """
        Check if an award detail page is published on USASpending.gov.

        Makes a GET request to the awards detail API endpoint to verify the award exists.

        Args:
            generated_internal_id: The generated_internal_id from search API
            timeout: HTTP request timeout in seconds

        Returns:
            True if award exists and is published, False otherwise
        """
        if not generated_internal_id:
            return False

        url = f"{USASPENDING_API_BASE}/api/v2/awards/{generated_internal_id}/"
        
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                # Check if response has actual award data
                data = response.json()
                return bool(data.get("id"))  # Award exists if it has an ID
            return False
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(
                "Error checking award publication for %s: %s",
                generated_internal_id,
                exc,
            )
            return False

    def _save_contract(self, parsed_data: Dict, overwrite: bool = False) -> Tuple[bool, bool]:
        """
        Save parsed contract.

        Returns:
            Tuple[bool, bool]: (saved, is_new)
        """
        award_id = parsed_data["award_id"]
        
        # Check existing
        existing = DefenseContract.objects.filter(
            data_source="usaspending",
            award_id=award_id,
        ).first()

        if existing:
            if not overwrite:
                logger.debug("Skipping duplicate award_id: %s", award_id)
                return False, False
            
            # Need to update existing record
            for key, value in parsed_data.items():
                setattr(existing, key, value)
            existing.save()
            logger.debug("Updated contract: %s", award_id)
            return True, False

        # Create new
        if parsed_data.get("data_source") == "usaspending":
            gen_id = parsed_data.get("generated_internal_id")
            if gen_id:
                parsed_data["usaspending_published"] = self.check_award_published(gen_id)

        try:
            DefenseContract.objects.create(**parsed_data)
            logger.debug("Created contract: %s", award_id)
            return True, True
        except IntegrityError:
            return False, False


__all__ = ["USASpendingService", "USASpendingAPIError"]
