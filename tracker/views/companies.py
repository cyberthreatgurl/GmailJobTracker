"""Companies views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

# pyright: reportAttributeAccessIssue=false, reportPossiblyUnboundVariable=false
# pyright: reportOptionalMemberAccess=false, reportArgumentType=false, reportCallIssue=false
# pylint: disable=broad-exception-caught

import json
import importlib
import logging
import os
import re
import subprocess
import sys
from urllib.parse import urlparse
from difflib import SequenceMatcher
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q, Count, F
from django.db.models.functions import Lower
from django.utils.timezone import now
from tracker.views.applications import check_for_existing_rejection
from tracker.models import (
    Company,
    CompanyOperatingCity,
    Message,
    ThreadTracking,
    AuditEvent,
)
from tracker.services.news_service import NewsAggregator
from tracker.services.browser_scraper import (
    fetch_best_effort_page,
    fetch_rendered_page,
    should_fallback_to_browser,
    should_use_browser_first,
)
from tracker.services.usaspending_service import USASpendingService
from tracker.forms import CompanyEditForm
from tracker.location_normalization import canonicalize_city_key
from tracker.views.helpers import build_sidebar_context
from tracker.utils.companies_io import companies_store

try:
    from country_state_city import Country, State
except Exception:  # pragma: no cover - optional dependency fallback
    Country = None
    State = None


def _get_parser_module():
    """Load the local parser module without a direct deprecated-module import."""
    return importlib.import_module("parser")


def _extract_homepage_domain(homepage_url):
    """Return the normalized domain portion of a homepage URL."""
    if not homepage_url:
        return ""

    parsed = urlparse(homepage_url)
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _synchronized_domain(domain_value, homepage_url):
    """Prefer the domain derived from homepage when a homepage is present."""
    homepage_domain = _extract_homepage_domain(homepage_url)
    if homepage_domain:
        return homepage_domain
    return (domain_value or "").strip().lower()

# Module-level constants
python_path = sys.executable
logger = logging.getLogger(__name__)

US_STATES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
    'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA',
    'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
    'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS',
    'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH',
    'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
    'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
    'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD', 'tennessee': 'TN',
    'texas': 'TX', 'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
    'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY', 'district of columbia': 'DC',
    'puerto rico': 'PR'
}

CANADA_PROVINCES = {
    'alberta': 'AB',
    'british columbia': 'BC',
    'manitoba': 'MB',
    'new brunswick': 'NB',
    'newfoundland and labrador': 'NL',
    'northwest territories': 'NT',
    'nova scotia': 'NS',
    'nunavut': 'NU',
    'ontario': 'ON',
    'prince edward island': 'PE',
    'quebec': 'QC',
    'saskatchewan': 'SK',
    'yukon': 'YT',
}

COUNTRY_ALIASES = {
    'united states': 'United States',
    'united states of america': 'United States',
    'usa': 'United States',
    'u.s.a.': 'United States',
    'us': 'United States',
    'u.s.': 'United States',
    'canada': 'Canada',
    'australia': 'Australia',
    'united kingdom': 'United Kingdom',
}


def _library_region_tokens():
    """Return region names/codes from country_state_city when available."""
    tokens = set()
    if State is None:
        return tokens

    try:
        for state in State.get_states():
            if state.name:
                tokens.add(state.name.lower())
            if state.iso_code:
                tokens.add(state.iso_code.upper())
    except Exception:
        logger.exception("Failed loading library region tokens")
    return tokens


def _library_country_tokens():
    """Return country names/codes from country_state_city when available."""
    tokens = set()
    if Country is None:
        return tokens

    try:
        for country in Country.get_countries():
            if country.name:
                tokens.add(country.name.lower())
            if country.iso2:
                tokens.add(country.iso2.upper())
    except Exception:
        logger.exception("Failed loading library country tokens")
    return tokens

REGION_TOKENS = sorted(
    set(US_STATES)
    | set(US_STATES.values())
    | set(CANADA_PROVINCES)
    | set(CANADA_PROVINCES.values())
    | _library_region_tokens(),
    key=len,
    reverse=True,
)
COUNTRY_TOKENS = sorted(
    set(COUNTRY_ALIASES) | set(COUNTRY_ALIASES.values()) | _library_country_tokens(),
    key=len,
    reverse=True,
)
REGION_PATTERN = "(?:" + "|".join(re.escape(token) for token in REGION_TOKENS) + ")"
COUNTRY_PATTERN = "(?:" + "|".join(re.escape(token) for token in COUNTRY_TOKENS) + ")"
CITY_PATTERN = r"(?-i:[A-Z][A-Za-z0-9.&\-/']*(?:\s+[A-Z][A-Za-z0-9.&\-/']*){0,4})"

INVALID_LOCATION_PARTS = {
    'apply', 'category', 'city', 'company', 'corp', 'country', 'dear', 'field',
    'hello', 'job', 'jobs', 'ltd', 'llc', 'location', 'locations', 'posted date',
    'province', 'save', 'search', 'state'
}

LOCATION_PATTERNS = [
    re.compile(
        rf'\bLocation\s*({CITY_PATTERN}),\s*({REGION_PATTERN})(?:,\s*({COUNTRY_PATTERN}))?'
        r'(?=\s*(?:\||Category|Categories|Job\s*Id|Posted\s*Date|Save|$))'
    , re.I),
    re.compile(
        rf'\bLocation\s*({CITY_PATTERN}),\s*({REGION_PATTERN})(?:\s+({COUNTRY_PATTERN}))?'
        r'(?=\s*(?:\||Category|Categories|Job\s*Id|Posted\s*Date|Save|$))'
    , re.I),
    re.compile(
        rf'\b({CITY_PATTERN}),\s*({REGION_PATTERN})(?:,\s*({COUNTRY_PATTERN}))?'
        r'(?=\s*(?:\||\.|!|;|<|$|Category|Categories|Job\s*Id|Posted\s*Date|Save|as\s+well\s+as|and\b))'
    , re.I),
]


def _clean_location_part(value):
    """Normalize a candidate location token from scraped HTML/text."""
    cleaned = re.sub(r'\s+', ' ', (value or '').replace('\xa0', ' ')).strip(' ,|:-')
    cleaned = re.sub(r'^(?:location|locations?)\s*', '', cleaned, flags=re.I)
    return cleaned.strip()


def _normalize_lookup_key(value):
    """Create a forgiving lookup key for location names."""
    cleaned = _clean_location_part(value).lower()
    cleaned = cleaned.replace('&', ' and ')
    cleaned = re.sub(r'[^a-z0-9]+', ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


@lru_cache(maxsize=1)
def _country_lookup_maps():
    """Build cached country lookups from country_state_city when available."""
    by_key = {}
    iso_to_name = {}
    if Country is None:
        return by_key, iso_to_name

    try:
        for country in Country.get_countries():
            iso_code = country.iso2.upper()
            iso_to_name[iso_code] = country.name
            by_key[_normalize_lookup_key(country.name)] = iso_code
            by_key[_normalize_lookup_key(country.iso2)] = iso_code
    except Exception:
        logger.exception("Failed to build country lookup maps")
    return by_key, iso_to_name


@lru_cache(maxsize=1)
def _state_lookup_maps():
    """Build cached state/province lookups from country_state_city when available."""
    by_country = {}
    global_unique = {}
    if State is None:
        return by_country, global_unique

    try:
        for state in State.get_states():
            country_code = state.country_code.upper()
            state_code = state.iso_code.upper()
            state_map = by_country.setdefault(country_code, {})
            state_map[_normalize_lookup_key(state.name)] = state_code
            state_map[_normalize_lookup_key(state.iso_code)] = state_code

            key = _normalize_lookup_key(state.name)
            if key not in global_unique:
                global_unique[key] = state_code
            elif global_unique[key] != state_code:
                global_unique[key] = None
    except Exception:
        logger.exception("Failed to build state lookup maps")
    return by_country, global_unique


def _resolve_country_name_and_code(country):
    """Resolve a normalized country name and ISO2 code when possible."""
    cleaned = _clean_location_part(country)
    if not cleaned:
        return None, None

    alias_name = COUNTRY_ALIASES.get(cleaned.lower())
    if alias_name:
        cleaned = alias_name

    lookup, iso_to_name = _country_lookup_maps()
    country_code = lookup.get(_normalize_lookup_key(cleaned))
    if country_code:
        return iso_to_name.get(country_code, cleaned.title()), country_code

    upper = cleaned.upper()
    if len(cleaned) == 2 and upper in iso_to_name:
        return iso_to_name[upper], upper
    return cleaned.title(), None


def _normalize_region(region, country=None):
    """Normalize state/province names to common abbreviations when known."""
    cleaned = _clean_location_part(region)
    lowered = cleaned.lower()
    if lowered in US_STATES:
        return US_STATES[lowered]
    if lowered in CANADA_PROVINCES:
        return CANADA_PROVINCES[lowered]
    upper = cleaned.upper()
    if upper in set(US_STATES.values()) | set(CANADA_PROVINCES.values()):
        return upper

    _, country_code = _resolve_country_name_and_code(country)
    by_country, global_unique = _state_lookup_maps()
    if country_code:
        state_code = by_country.get(country_code, {}).get(_normalize_lookup_key(cleaned))
        if state_code:
            return state_code

    unique_state_code = global_unique.get(_normalize_lookup_key(cleaned))
    if unique_state_code:
        return unique_state_code

    if len(cleaned) <= 4 and cleaned.isupper():
        return cleaned
    return cleaned.title() if cleaned else cleaned


def _normalize_country(country):
    """Normalize country names while preserving unknown values."""
    normalized_name, _ = _resolve_country_name_and_code(country)
    return normalized_name


def _build_location(city, region, country=None):
    """Build a normalized location string from candidate parts."""
    city_clean = _clean_location_part(city)
    country_clean = _normalize_country(country)
    region_clean = _normalize_region(region, country_clean)

    if not city_clean or not region_clean:
        return None
    if city_clean.lower() in INVALID_LOCATION_PARTS:
        return None
    if region_clean.lower() in INVALID_LOCATION_PARTS:
        return None
    if any(char.isdigit() for char in city_clean) and ',' not in city_clean:
        return None
    if city_clean.lower().startswith('available in '):
        return None

    if country_clean in (None, '', 'United States'):
        return f"{city_clean}, {region_clean}"
    return f"{city_clean}, {region_clean}, {country_clean}"


def _add_locations_from_candidate_string(candidate, add_location):
    """Parse a comma-separated location string and add it if valid."""
    cleaned = _clean_location_part(candidate)
    if not cleaned:
        return

    for segment in re.split(r'\s*;\s*', cleaned):
        _add_single_location_candidate(segment, add_location)


def _add_single_location_candidate(candidate, add_location):
    """Parse a single location candidate and add it if valid."""
    cleaned = _clean_location_part(candidate)
    if not cleaned or ',' not in cleaned:
        return

    primary = cleaned.split('|', 1)[0].strip()
    parts = [part.strip() for part in primary.split(',') if part.strip()]
    while parts and re.fullmatch(r'[A-Z0-9\- ]{3,12}', parts[-1]):
        parts.pop()

    if len(parts) >= 3:
        add_location(parts[0], parts[1], parts[2])
    elif len(parts) >= 2:
        add_location(parts[0], parts[1])

def _extract_locations_from_html(html_content):
    """Extracts locations from HTML and formats them to 'City, State' or 'City, Country'."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    locations = set()

    def add_location(city, region, country=None):
        location = _build_location(city, region, country)
        if location:
            locations.add(location)

    # 1. Target the specific provided HTML structure
    location_blocks = soup.find_all(class_=re.compile(r'location-block', re.I))
    for block in location_blocks:
        parts = block.find_all(class_=re.compile(r'results-location', re.I))
        # Filter out empty div tags
        valid_parts = [p.get_text(strip=True) for p in parts if p.get_text(strip=True)]

        if len(valid_parts) >= 2:
            city = valid_parts[0]
            region = valid_parts[1]

            # Capture City, Province, Country if available
            if len(valid_parts) >= 3:
                add_location(city, region, valid_parts[2])
                continue

            add_location(city, region)

    # 2. Parse JSON/script-backed location strings commonly used by job sites.
    for match in re.finditer(
        r'"(?:multi_location|location|address)"\s*:\s*(?:\[\s*)?"([^"]+)"',
        html_content,
        re.I,
    ):
        _add_locations_from_candidate_string(match.group(1), add_location)

    # 3. General text fallback for search results and plain text snippets.
    text = soup.get_text(separator=' | ', strip=True)
    normalized_text = re.sub(r'\bLocation(?=[A-Z])', 'Location ', text)
    normalized_text = re.sub(r'\s+', ' ', normalized_text)

    for pattern in LOCATION_PATTERNS:
        for match in pattern.finditer(normalized_text):
            city = match.group(1)
            region = match.group(2)
            country = match.group(3) if match.lastindex and match.lastindex >= 3 else None
            add_location(city, region, country)

    return sorted([loc for loc in locations if loc and len(loc) > 4])


def _extract_locations_from_captured_json(captured_json):
    """Extract normalized locations from captured ATS JSON payloads."""
    locations = set()

    def add_location(city, region, country=None):
        location = _build_location(city, region, country)
        if location:
            locations.add(location)

    for item in captured_json or []:
        payload = item.get("data") if isinstance(item, dict) else None
        if not isinstance(payload, dict):
            continue

        search_locations = payload.get("locations") or []
        for search_location in search_locations:
            _add_locations_from_candidate_string(search_location, add_location)

        for job in payload.get("jobs") or []:
            job_data = job.get("data", job) if isinstance(job, dict) else None
            if not isinstance(job_data, dict):
                continue

            city = job_data.get("city")
            region = job_data.get("state") or job_data.get("region")
            country = job_data.get("country") or job_data.get("country_code")
            if city and region:
                add_location(city, region, country)

            for key in ("location", "location_name", "full_location", "short_location"):
                value = job_data.get(key)
                if value:
                    _add_locations_from_candidate_string(value, add_location)

            multi_locations = job_data.get("multipleLocations") or job_data.get("multi_location") or []
            if isinstance(multi_locations, bool):
                multi_locations = []
            elif isinstance(multi_locations, str):
                multi_locations = [multi_locations]
            for entry in multi_locations:
                if entry:
                    _add_locations_from_candidate_string(entry, add_location)

    return sorted(locations)

def _parse_operating_cities(raw_text):
    """Parse multiline city input into unique cleaned city names.

    Accepts one city per line and performs case-insensitive deduplication while
    preserving first-seen order.
    """
    lines = (raw_text or "").splitlines()
    seen = set()
    cities = []
    for line in lines:
        city = re.sub(r"\s+", " ", line.strip())
        if not city:
            continue
        key = canonicalize_city_key(city)
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        cities.append(city[:255])
    return cities


def _sync_company_operating_cities(company, raw_text):
    """Upsert additional operating cities for a company from multiline input."""
    if not company:
        return
    desired = _parse_operating_cities(raw_text)
    desired_keys = {canonicalize_city_key(city) for city in desired}

    existing = list(CompanyOperatingCity.objects.filter(company=company))
    existing_by_key = {}
    duplicate_ids = set()

    for row in existing:
        key = canonicalize_city_key(row.city)
        if not key:
            duplicate_ids.add(row.id)
            continue
        if key in existing_by_key:
            duplicate_ids.add(row.id)
            continue
        existing_by_key[key] = row

    if duplicate_ids:
        CompanyOperatingCity.objects.filter(id__in=duplicate_ids).delete()

    # Delete removed cities
    for key, row in existing_by_key.items():
        if key not in desired_keys:
            row.delete()

    # Create missing cities
    for city in desired:
        key = canonicalize_city_key(city)
        if key not in existing_by_key:
            CompanyOperatingCity.objects.create(company=company, city=city)


def _normalize_city_for_match(value):
    """Normalize city/location text for matching."""
    return canonicalize_city_key(value)


def _company_matches_city(company, search_city_normalized, threshold=0.82):
    """Return True if company HQ/additional cities match exact, partial, or fuzzy city query."""
    if not search_city_normalized:
        return False

    candidate_texts = []

    if company.location:
        location_norm = _normalize_city_for_match(company.location)
        if location_norm:
            candidate_texts.append(location_norm)
            city_part = location_norm.split(",", 1)[0].strip()
            if city_part and city_part != location_norm:
                candidate_texts.append(city_part)

    for row in getattr(company, "operating_cities", []).all():
        city_norm = _normalize_city_for_match(row.city)
        if city_norm:
            candidate_texts.append(city_norm)

    for text in candidate_texts:
        if search_city_normalized in text or text in search_city_normalized:
            return True
        if SequenceMatcher(None, search_city_normalized, text).ratio() >= threshold:
            return True

    return False


def _scrape_and_analyze_company(homepage_url, timeout=10):
    """
    Shared helper function to scrape company info and perform sentiment analysis.

    Args:
        homepage_url: The URL to scrape
        timeout: Request timeout in seconds

    Returns:
        dict: Scraped data with keys: name, domain, career_url, page_content, focus_analysis

    Raises:
        CompanyScraperError: If scraping fails
    """
    from tracker.services.company_scraper import scrape_company_info, analyze_company_focus

    # Scrape company information
    scraped_data = scrape_company_info(homepage_url, timeout=timeout)

    # Extract page content and perform sentiment analysis
    page_content = scraped_data.get("page_content", "")
    pages_scraped = scraped_data.get("pages_scraped", ["homepage"])

    focus_analysis = analyze_company_focus(page_content) if page_content else ""

    # Add scraping metadata to focus analysis
    if focus_analysis and pages_scraped:
        page_list = ", ".join(pages_scraped)
        focus_analysis = f"📄 Analyzed pages: {page_list}\n\n{focus_analysis}"

    # Add focus analysis to scraped data
    scraped_data["focus_analysis"] = focus_analysis

    return scraped_data


@login_required
def delete_company(request, company_id):
    """Delete a company and all related messages/applications, then retrain model."""
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        messages.error(
            request,
            f"❌ Company with ID {company_id} not found. It may have already been deleted.",
        )
        return redirect("label_companies")

    if request.method == "POST":
        company_name = company.name

        # Count related data before deletion (including noise messages)
        total_message_count = Message.objects.filter(company=company).count()
        noise_message_count = Message.objects.filter(
            company=company, ml_label="noise"
        ).count()
        non_noise_message_count = total_message_count - noise_message_count
        application_count = ThreadTracking.objects.filter(company=company).count()

        # Delete all related messages, applications, etc.
        Message.objects.filter(company=company).delete()
        ThreadTracking.objects.filter(company=company).delete()
        # Remove company itself
        company.delete()

        # Show detailed deletion info
        messages.success(request, f"✅ Company '{company_name}' deleted successfully.")
        if noise_message_count > 0:
            messages.info(
                request,
                f"📊 Removed {non_noise_message_count} messages "
                f"({noise_message_count} noise) and {application_count} "
                "applications.",
            )
        else:
            messages.info(
                request,
                f"📊 Removed {total_message_count} messages and {application_count} applications.",
            )

        # Trigger model retraining in background
        messages.info(request, "🔄 Retraining model to update training data...")
        try:
            result = subprocess.run(
                [python_path, "train_model.py"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0:
                messages.success(
                    request, "✅ Model retrained successfully. Training data updated."
                )
            else:
                messages.warning(
                    request,
                    f"⚠️ Model retraining encountered issues. You may need to retrain manually.",
                )
        except subprocess.TimeoutExpired:
            messages.warning(
                request,
                "⚠️ Model retraining timed out. Please retrain manually from the sidebar.",
            )
        except Exception as e:
            messages.warning(
                request,
                f"⚠️ Could not auto-retrain model: {str(e)}. Please retrain manually.",
            )

        return redirect("label_companies")
    ctx = {"company": company}
    return render(request, "tracker/delete_company.html", ctx)


@login_required
def label_companies(request):
    """List companies for labeling and provide quick actions (create/select/update)."""
    from urllib.parse import quote

    # Quick Add Company action - redirect to new company form instead of creating immediately
    if request.method == "POST" and request.POST.get("action") == "quick_add_company":
        from urllib.parse import urlparse

        homepage_url = request.POST.get("homepage_url", "").strip()
        if not homepage_url:
            messages.error(request, "❌ Please enter a homepage URL.")
            return redirect("label_companies")

        # Add https:// if missing
        if not homepage_url.startswith(("http://", "https://")):
            homepage_url = "https://" + homepage_url

        # Validate URL syntax
        try:
            parsed = urlparse(homepage_url)
            if not parsed.netloc:
                messages.error(request, "❌ Invalid URL format. Please enter a valid URL.")
                return redirect("label_companies")
        except Exception:
            messages.error(request, "❌ Invalid URL format. Please enter a valid URL.")
            return redirect("label_companies")

        # Scrape company info
        try:
            scraped_data = _scrape_and_analyze_company(homepage_url, timeout=10)
            company_name = scraped_data.get("name", "")
            domain = scraped_data.get("domain", "")
            career_url = scraped_data.get("career_url", "")
            focus_analysis = scraped_data.get("focus_analysis", "")

            # Check if company already exists in database by name or domain
            existing = None
            if company_name:
                existing = Company.objects.filter(name__iexact=company_name).first()
            if not existing and domain:
                existing = Company.objects.filter(domain__iexact=domain).first()

            if existing:
                messages.info(
                    request, f"ℹ️ Company '{existing.name}' already exists in database."
                )
                return redirect(f"/label_companies/?company={existing.id}")

            # Check if company exists in companies.json
            companies_json_path = Path("json/companies.json")
            if companies_json_path.exists():
                try:
                    with open(companies_json_path, "r", encoding="utf-8") as f:
                        companies_json_data = json.load(f)

                    found_in_json = None

                    # Check if scraped name is in known companies list
                    if company_name and "known" in companies_json_data:
                        for known_name in companies_json_data["known"]:
                            if known_name.lower() == company_name.lower():
                                found_in_json = known_name
                                break

                    # Check if domain maps to a known company
                    if not found_in_json and domain and "domain_to_company" in companies_json_data:
                        if domain in companies_json_data["domain_to_company"]:
                            found_in_json = companies_json_data["domain_to_company"][domain]

                    if found_in_json:
                        # Company exists in companies.json - check if Company record exists
                        existing = Company.objects.filter(name__iexact=found_in_json).first()
                        if existing:
                            messages.info(
                                request, f"ℹ️ Company '{existing.name}' already exists (found in companies.json)."
                            )
                            return redirect(f"/label_companies/?company={existing.id}")
                        else:
                            # Create Company record from companies.json entry
                            new_company = Company.objects.create(
                                name=found_in_json,
                                domain=domain or "",
                                homepage=homepage_url,
                                career_url=career_url or "",
                                confidence=1.0,
                                first_contact=now(),
                                last_contact=now(),
                                status="application"
                            )
                            messages.success(
                                request, f"✅ Created company '{new_company.name}' from known companies list."
                            )
                            return redirect(f"/label_companies/?company={new_company.id}")

                except Exception as e:
                    # If companies.json check fails, continue with normal flow
                    logger.exception(f"Failed to check companies.json: {e}")

            # Redirect to new company form with scraped data
            params = []
            if company_name:
                params.append(f"new_company_name={quote(company_name)}")
            if homepage_url:
                params.append(f"homepage={quote(homepage_url)}")
            if domain:
                params.append(f"domain={quote(domain)}")
            if career_url:
                params.append(f"career_url={quote(career_url)}")
            if focus_analysis:
                params.append(f"notes={quote(focus_analysis)}")

            redirect_url = f"/label_companies/?{'&'.join(params)}"
            messages.success(request, f"✅ Scraped company info from {domain}. Review and save below.")
            return redirect(redirect_url)

        except Exception as e:
            logger.exception(f"Failed to scrape company info from {homepage_url}")
            messages.error(request, f"❌ Failed to scrape company info: {e}")
            # Still allow manual entry by redirecting to form with just the URL
            return redirect(f"/label_companies/?homepage={quote(homepage_url)}")

    # Exclude headhunter companies from the dropdown
    companies = Company.objects.exclude(status="headhunter").order_by(Lower("name"))
    # Preserve selected company on POST actions as well
    selected_id = request.GET.get("company") or request.POST.get("company")
    selected_company = None
    latest_label = None
    last_message_ts = None
    days_since_last_message = None

    # Check for new company creation mode (Quick Add prefill or dropdown selection)
    new_company_name = request.GET.get("new_company_name", "").strip()
    prefill_homepage = request.GET.get("homepage", "").strip()
    prefill_domain = request.GET.get("domain", "").strip()
    prefill_career_url = request.GET.get("career_url", "").strip()
    prefill_notes = request.GET.get("notes", "").strip()
    # Treat as new company creation if:
    # 1. We have prefill params from URL AND no selected_id, OR
    # 2. User selected "new" from dropdown, OR
    # 3. Form action is create_new_company or populate_from_homepage
    creating_new_company = bool(
        (new_company_name or prefill_homepage) and not selected_id or
        selected_id == "new" or
        request.POST.get("action") in ("create_new_company", "populate_from_homepage")
    )
    # Configurable threshold for ghosted hint (default 30). DB AppSetting overrides env.
    from tracker.models import AppSetting

    ghosted_days_threshold = 30
    try:
        db_val = (
            AppSetting.objects.filter(key="GHOSTED_DAYS_THRESHOLD")
            .values_list("value", flat=True)
            .first()
        )
        if db_val is not None and str(db_val).strip() != "":
            ghosted_days_threshold = int(str(db_val).strip())
        else:
            env_val = (
                (os.environ.get("GHOSTED_DAYS_THRESHOLD") or "")
                .strip()
                .replace('"', "")
            )
            if env_val:
                ghosted_days_threshold = int(env_val)
    except Exception:
        pass
    if ghosted_days_threshold < 1 or ghosted_days_threshold > 3650:
        ghosted_days_threshold = 30
    form = None
    message_count = 0
    message_info_list = []
    operating_cities_text = ""
    operating_cities_list = []
    if selected_id and selected_id != "new":
        try:
            selected_company = Company.objects.get(id=selected_id)
            # Load career URL from companies.json JobSites
            companies_json_path = Path("json/companies.json")
            career_url = ""
            alias = ""
            try:
                if companies_json_path.exists():
                    with open(companies_json_path, "r", encoding="utf-8") as f:
                        companies_json_data = json.load(f)
                        career_url = companies_json_data.get("JobSites", {}).get(
                            selected_company.name, ""
                        )
                        # Load all aliases for this company (reverse lookup in aliases dict)
                        # Check both: canonical names that match AND if company name is itself an alias
                        aliases_dict = companies_json_data.get("aliases", {})

                        # Find canonical name for this company (if it's an alias)
                        canonical_name = aliases_dict.get(selected_company.name, selected_company.name)

                        # Collect all aliases that point to the canonical name
                        alias_list = [
                            alias_name
                            for alias_name, canonical in aliases_dict.items()
                            if canonical in (canonical_name, selected_company.name)
                        ]
                        alias = ", ".join(alias_list) if alias_list else ""
            except Exception:
                pass

            operating_cities_list = list(
                CompanyOperatingCity.objects.filter(company=selected_company)
                .values_list("city", flat=True)
            )
            operating_cities_text = "\n".join(operating_cities_list)
        except Company.DoesNotExist:
            selected_company = None
            messages.warning(
                request,
                f"⚠️ Company with ID {selected_id} not found. It may have been deleted.",
            )
        if selected_company:
            # Get latest label from messages
            latest_msg = (
                Message.objects.filter(company=selected_company, ml_label__isnull=False)
                .order_by("-timestamp")
                .first()
            )
            latest_label = latest_msg.ml_label if latest_msg else None

            # Get message count and (date, subject, label) list (exclude noise messages)
            messages_qs = (
                Message.objects.filter(company=selected_company)
                .exclude(ml_label="noise")
                .order_by("-timestamp")
            )
            message_count = messages_qs.count()
            # Provide (id, timestamp, subject, ml_label) for deep links to label_messages focus
            message_info_list = list(
                messages_qs.values_list("id", "timestamp", "subject", "ml_label")
            )
            # Compute days since last message for ghosted assessment
            if message_count > 0:
                last_message_ts = messages_qs.first().timestamp
                try:
                    days_since_last_message = (now() - last_message_ts).days
                except Exception:
                    days_since_last_message = None
            if request.method == "POST":
                # Re-ingest messages for selected company
                if request.POST.get("action") == "reingest_company":
                    try:
                        from gmail_auth import get_gmail_service

                        ingest_message = _get_parser_module().ingest_message
                        service = get_gmail_service()
                        if not service:
                            messages.error(
                                request, "❌ Failed to initialize Gmail service."
                            )
                        else:
                            # Find all message IDs for this company
                            # Include messages currently assigned to this company
                            company_messages_query = Message.objects.filter(
                                company=selected_company
                            )

                            # Also include messages from company's domain or ATS domain
                            domains_to_check = []
                            if selected_company.domain:
                                domains_to_check.append(selected_company.domain.strip().lower())
                            if selected_company.ats:
                                domains_to_check.append(selected_company.ats.strip().lower())

                            # Filter out broad ATS domains and common email providers
                            try:
                                with open("json/companies.json", "r", encoding="utf-8") as f:
                                    company_data = json.load(f)
                                ats_metadata = set(d.lower() for d in company_data.get("ats_domains", []))
                            except Exception:
                                ats_metadata = set()
                                logging.warning("Could not load ats_domains from companies.json")

                            common_providers = {
                                "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
                                "aol.com", "protonmail.com", "me.com", "msn.com", "live.com",
                                "googlemail.com", "yandex.com", "mail.com", "zoho.com"
                            }

                            safe_domains = []
                            for d in domains_to_check:
                                is_broad_ats = d in ats_metadata
                                is_common_provider = d in common_providers
                                if not is_broad_ats and not is_common_provider:
                                    safe_domains.append(d)
                                else:
                                    logging.warning(
                                        f"Skipping broad re-ingest domain '{d}' for company '{selected_company.name}'"
                                    )

                            # Build query to include sender domains
                            if safe_domains:
                                from django.db.models import Q

                                domain_query = Q()
                                for domain in safe_domains:
                                    domain_query |= Q(sender__icontains=f"@{domain}")

                                # Combine: messages assigned to company OR from company domains
                                company_messages_query = Message.objects.filter(
                                    Q(company=selected_company) | domain_query
                                ).distinct()

                            company_messages = company_messages_query.values(
                                "msg_id", "subject", "ml_label"
                            )

                            processed = 0
                            updated_labels = 0
                            errors = 0

                            for msg_info in company_messages[
                                :1000
                            ]:  # Limit to avoid timeout
                                try:
                                    old_label = msg_info["ml_label"]
                                    # Clear reviewed flag for messages reingested from the UI
                                    try:
                                        mobj = Message.objects.filter(
                                            msg_id=msg_info["msg_id"]
                                        ).first()
                                        if mobj:
                                            mobj.reviewed = False
                                            mobj.save(update_fields=["reviewed"])
                                            # Also clear ThreadTracking reviewed state for the thread
                                            if mobj.thread_id:
                                                ThreadTracking.objects.filter(
                                                    thread_id=mobj.thread_id
                                                ).update(reviewed=False)
                                    except Exception:
                                        # Best-effort: continue even if clearing fails
                                        logger.exception(
                                            f"Failed to clear reviewed for {msg_info['msg_id']}"
                                        )

                                    # Audit: record UI-initiated clear for traceability (batch/company reingest)
                                    try:
                                        audit_path = (
                                            Path("logs") / "clear_reviewed_audit.log"
                                        )
                                        audit_path.parent.mkdir(
                                            parents=True, exist_ok=True
                                        )
                                        entry = {
                                            "ts": now().isoformat(),
                                            "user": (
                                                request.user.username
                                                if hasattr(request, "user")
                                                else "unknown"
                                            ),
                                            "action": "ui_reingest_clear",
                                            "source": "reingest_company",
                                            "msg_id": msg_info["msg_id"],
                                            "company": (
                                                selected_company.name
                                                if selected_company
                                                else None
                                            ),
                                            "company_id": (
                                                selected_company.id
                                                if selected_company
                                                else None
                                            ),
                                            "thread_id": msg_info.get("thread_id"),
                                            "db_id": msg_info.get("id"),
                                            "pid": os.getpid(),
                                        }
                                        with open(
                                            audit_path, "a", encoding="utf-8"
                                        ) as af:
                                            af.write(
                                                json.dumps(entry, ensure_ascii=False)
                                                + "\n"
                                            )
                                        # Also persist to DB for easier querying
                                        try:
                                            AuditEvent.objects.create(
                                                user=entry.get("user"),
                                                action=entry.get("action"),
                                                source=entry.get("source"),
                                                msg_id=entry.get("msg_id"),
                                                db_id=entry.get("db_id"),
                                                thread_id=entry.get("thread_id"),
                                                company_id=entry.get("company_id"),
                                                details=json.dumps(
                                                    entry, ensure_ascii=False
                                                ),
                                                pid=entry.get("pid"),
                                            )
                                        except Exception:
                                            logger.exception(
                                                "Failed to write AuditEvent DB record for ui_reingest_clear"
                                            )
                                    except Exception as e:
                                        # Include stack trace in logger; also write a minimal audit entry with error
                                        logger.exception(
                                            "Failed to write audit log for UI reingest clear"
                                        )
                                        try:
                                            import traceback

                                            audit_path = (
                                                Path("logs")
                                                / "clear_reviewed_audit.log"
                                            )
                                            audit_path.parent.mkdir(
                                                parents=True, exist_ok=True
                                            )
                                            entry = {
                                                "ts": now().isoformat(),
                                                "user": (
                                                    request.user.username
                                                    if hasattr(request, "user")
                                                    else "unknown"
                                                ),
                                                "action": "ui_reingest_clear",
                                                "source": "reingest_company",
                                                "msg_id": msg_info["msg_id"],
                                                "error": str(e),
                                                "trace": traceback.format_exc(),
                                            }
                                            with open(
                                                audit_path, "a", encoding="utf-8"
                                            ) as af:
                                                af.write(
                                                    json.dumps(
                                                        entry, ensure_ascii=False
                                                    )
                                                    + "\n"
                                                )
                                            try:
                                                AuditEvent.objects.create(
                                                    user=entry.get("user"),
                                                    action=entry.get("action"),
                                                    source=entry.get("source"),
                                                    msg_id=entry.get("msg_id"),
                                                    details=json.dumps(
                                                        entry, ensure_ascii=False
                                                    ),
                                                    error=entry.get("error"),
                                                    trace=entry.get("trace"),
                                                )
                                            except Exception:
                                                logger.exception(
                                                    "Failed to write fallback "
                                                    "AuditEvent DB record for "
                                                    "ui_reingest_clear"
                                                )
                                        except Exception:
                                            logger.exception(
                                                "Also failed to write error audit for UI reingest clear"
                                            )

                                    # Suppress auto-mark-reviewed during this UI-initiated re-ingest
                                    try:
                                        os.environ["SUPPRESS_AUTO_REVIEW"] = "1"
                                        ingest_message(service, msg_info["msg_id"])
                                    finally:
                                        try:
                                            del os.environ["SUPPRESS_AUTO_REVIEW"]
                                        except Exception:
                                            pass

                                    # Check if label changed
                                    updated_msg = Message.objects.get(
                                        msg_id=msg_info["msg_id"]
                                    )
                                    if updated_msg.ml_label != old_label:
                                        updated_labels += 1

                                    processed += 1
                                except Exception as e:
                                    errors += 1
                                    logger.error(
                                        f"Error re-ingesting {msg_info['msg_id']}: {e}"
                                    )

                            messages.success(
                                request,
                                f"✅ Re-ingested {processed} messages for {selected_company.name}. "
                                f"{updated_labels} labels updated. {errors} errors.",
                            )
                    except Exception as e:
                        messages.error(request, f"⚠️ Error during re-ingestion: {e}")
                        logger.exception("Re-ingestion error")

                    return redirect(f"/label_companies/?company={selected_company.id}")

                # Populate company info from homepage
                if request.POST.get("action") == "populate_from_homepage":
                    homepage_url = request.POST.get("homepage", "").strip()
                    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    operating_cities_text = request.POST.get(
                        "operating_cities_text", operating_cities_text
                    )

                    save_before_populate_form = CompanyEditForm(
                        request.POST, instance=selected_company
                    )
                    if not save_before_populate_form.is_valid():
                        if is_ajax:
                            errors = '; '.join(
                                [
                                    f"{field}: {', '.join(errs)}"
                                    for field, errs in save_before_populate_form.errors.items()
                                ]
                            )
                            return JsonResponse(
                                {
                                    'success': False,
                                    'message': f'Please fix validation errors before populate: {errors}',
                                }
                            )
                        form = save_before_populate_form
                        messages.error(
                            request,
                            "❌ Please fix form errors before clicking Populate.",
                        )
                    else:
                        save_before_populate_form.save()
                        _sync_company_operating_cities(
                            selected_company, operating_cities_text
                        )

                    if not homepage_url and is_ajax:
                        return JsonResponse(
                            {
                                'success': False,
                                'message': 'Please enter a homepage URL first.',
                            }
                        )
                    if not homepage_url:
                        messages.error(request, "❌ Please enter a homepage URL first.")
                    elif save_before_populate_form.is_valid():
                        try:
                            scraped_data = _scrape_and_analyze_company(homepage_url)

                            # Append focus analysis to notes if available
                            focus_analysis = scraped_data.get("focus_analysis", "")
                            notes_to_return = focus_analysis
                            if focus_analysis:
                                current_notes = selected_company.notes or ""
                                if current_notes:
                                    selected_company.notes = f"{current_notes}\n\n{focus_analysis}"
                                else:
                                    selected_company.notes = focus_analysis
                                selected_company.save(update_fields=["notes"])

                            # Return JSON for AJAX requests
                            if is_ajax:
                                success_msg = "Successfully scraped company info from homepage."
                                if not scraped_data.get("career_url"):
                                    success_msg = "Company name extracted. Career page not found automatically."

                                return JsonResponse({
                                    'success': True,
                                    'message': success_msg,
                                    'name': scraped_data.get("name", ""),
                                    'domain': scraped_data.get("domain", ""),
                                    'career_url': scraped_data.get("career_url", ""),
                                    'notes': notes_to_return
                                })

                            # Create a form with the scraped data, preserving user-entered fields
                            form_data = {
                                "name": scraped_data.get("name", selected_company.name),
                                "domain": scraped_data.get("domain", selected_company.domain),
                                "homepage": homepage_url,
                                "career_url": scraped_data.get("career_url", ""),
                                "talent_network": request.POST.get(
                                    "talent_network",
                                    "on" if selected_company.talent_network else "",
                                ),
                                "ats": request.POST.get("ats", selected_company.ats or ""),
                                "contact_name": request.POST.get(
                                    "contact_name",
                                    selected_company.contact_name or "",
                                ),
                                "contact_email": request.POST.get(
                                    "contact_email",
                                    selected_company.contact_email or "",
                                ),
                                "status": request.POST.get(
                                    "status",
                                    selected_company.status or "application",
                                ),
                                "focus_area": request.POST.get(
                                    "focus_area",
                                    selected_company.focus_area or "",
                                ),
                                "alias": alias,  # Preserve alias from companies.json
                            }
                            form = CompanyEditForm(form_data, instance=selected_company)
                            operating_cities_text = request.POST.get(
                                "operating_cities_text", operating_cities_text
                            )

                            # Show success or partial success message
                            if scraped_data.get("career_url"):
                                messages.success(
                                    request,
                                    "✅ Successfully scraped company info from "
                                    "homepage. Review and click Save Changes to "
                                    "apply.",
                                )
                            else:
                                messages.success(
                                    request,
                                    "✅ Company name extracted. Career page not "
                                    "found automatically. Please enter it manually "
                                    "if known.",
                                )
                        except Exception as e:
                            logger.exception(
                                "Failed to scrape homepage for existing company: %s",
                                homepage_url,
                            )

                            # Write error to notes field
                            error_msg = f"❌ Populate Error ({homepage_url}):\n{str(e)}"
                            current_notes = selected_company.notes or ""
                            if current_notes:
                                updated_notes = f"{current_notes}\n\n{error_msg}"
                            else:
                                updated_notes = error_msg
                            selected_company.notes = updated_notes
                            selected_company.save(update_fields=["notes"])

                            # Return JSON for AJAX requests
                            if is_ajax:
                                return JsonResponse(
                                    {
                                        'success': False,
                                        'message': str(e),
                                        'notes': error_msg,
                                    }
                                )

                            messages.error(request, f"❌ Failed to scrape homepage: {e}")
                            form = CompanyEditForm(instance=selected_company, initial={"career_url": career_url})
                            operating_cities_text = request.POST.get(
                                "operating_cities_text", operating_cities_text
                            )
                    # Don't redirect - stay on page with populated form

                # Quick action: mark as ghosted
                elif request.POST.get("action") == "save_notes":
                    # Save notes for the selected company
                    try:
                        notes_text = request.POST.get("notes", "").strip()
                        selected_company.notes = notes_text if notes_text else None
                        selected_company.save(update_fields=["notes"])
                        messages.success(
                            request,
                            f"✅ Notes saved for {selected_company.name}.",
                        )
                    except Exception as e:
                        messages.error(request, f"❌ Failed to save notes: {e}")
                    return redirect(f"/label_companies/?company={selected_company.id}")

                # Save application details (prescreen/interview dates, URL, text)
                elif request.POST.get("action") == "save_application_details":
                    try:
                        from tracker.forms_company import ApplicationDetailsForm

                        # Get thread_id from POST data (user selects which application to edit)
                        thread_id = request.POST.get("thread_id", "").strip()
                        is_new_manual_entry = False

                        if thread_id:
                            # Edit existing ThreadTracking
                            thread_tracking = ThreadTracking.objects.filter(
                                thread_id=thread_id,
                                company=selected_company
                            ).first()

                            if not thread_tracking:
                                messages.error(request, f"❌ Application thread not found: {thread_id}")
                                return redirect(f"/label_companies/?company={selected_company.id}")
                        else:
                            # Create a new manual ThreadTracking if no thread_id specified
                            thread_tracking = ThreadTracking.objects.create(
                                thread_id=f"manual_{selected_company.id}_{now().timestamp()}",
                                company=selected_company,
                                job_title="Manual Entry",
                                status="application",
                                sent_date=now().date(),
                            )
                            is_new_manual_entry = True

                        form_data = ApplicationDetailsForm(request.POST, instance=thread_tracking)
                        if form_data.is_valid():
                            form_data.save()

                            # For new manual entries, check for existing rejection/cancelled messages
                            rejection_merged = False
                            if is_new_manual_entry:
                                rejection_merged = check_for_existing_rejection(thread_tracking, selected_company)

                            job_title = thread_tracking.job_title or "this application"
                            success_msg = f"✅ Application details saved for {selected_company.name} - {job_title}."
                            if rejection_merged:
                                rejection_type = "cancelled" if thread_tracking.cancelled else "rejected"
                                success_msg += f" (📧 Found existing {rejection_type} message - status updated)"
                            messages.success(request, success_msg)
                        else:
                            for field, errors in form_data.errors.items():
                                for error in errors:
                                    messages.error(request, f"❌ {field}: {error}")
                    except Exception as e:
                        messages.error(request, f"❌ Failed to save application details: {e}")
                        logger.exception("Failed to save application details")
                    return redirect(f"/label_companies/?company={selected_company.id}")

                # Handle "mark_searched" checkbox
                if request.POST.get("mark_searched"):
                    try:
                        selected_company.last_job_search_date = now()
                        selected_company.save(update_fields=["last_job_search_date"])
                        messages.success(
                            request,
                            "✅ Marked "
                            f"{selected_company.name} as searched on "
                            f"{selected_company.last_job_search_date.strftime('%Y-%m-%d %H:%M')}",
                        )
                    except Exception as e:
                        messages.error(request, f"❌ Failed to mark as searched: {e}")
                    return redirect(f"/label_companies/?company={selected_company.id}")

                # Handle regular form submission (Save Changes)
                elif not request.POST.get("action"):  # No action means it's the main form
                    form = CompanyEditForm(request.POST, instance=selected_company)
                    operating_cities_text = request.POST.get("operating_cities_text", "")
                    if form.is_valid():
                        # Get cleaned data before saving
                        career_url_input = (
                            form.cleaned_data.get("career_url") or ""
                        ).strip()
                        homepage_input = (form.cleaned_data.get("homepage") or "").strip()
                        domain_input = _synchronized_domain(
                            form.cleaned_data.get("domain"),
                            homepage_input,
                        )
                        ats_input = (form.cleaned_data.get("ats") or "").strip()
                        company_name = selected_company.name
                        form.instance.domain = domain_input

                        # Save company-side fields to companies.json surgically
                        if company_name:
                            try:
                                alias_input = (form.cleaned_data.get("alias") or "").strip()
                                new_aliases = (
                                    [a.strip() for a in alias_input.split(",") if a.strip()]
                                    if alias_input
                                    else []
                                )
                                companies_store.update_company(
                                    company_name,
                                    new_domain=domain_input,
                                    career_url=career_url_input,
                                    ats_domain=ats_input or None,
                                    new_aliases=new_aliases,
                                    source="companies.save_company",
                                )
                            except Exception as e:
                                messages.warning(
                                    request, f"⚠️ Failed to update companies.json: {e}"
                                )

                        # Sync aliases to CompanyAlias DB table so they survive
                        # companies.json restores and are checked at ingest time.
                        try:
                            from tracker.models import CompanyAlias as DBCompanyAlias
                            alias_input_db = (form.cleaned_data.get("alias") or "").strip()
                            if alias_input_db:
                                new_db_aliases = [a.strip() for a in alias_input_db.split(",") if a.strip()]
                                DBCompanyAlias.objects.filter(company=company_name).exclude(
                                    alias__in=new_db_aliases
                                ).delete()
                                for db_alias in new_db_aliases:
                                    DBCompanyAlias.objects.update_or_create(
                                        alias=db_alias,
                                        defaults={"company": company_name},
                                    )
                            else:
                                DBCompanyAlias.objects.filter(company=company_name).delete()
                        except Exception as e:
                            logger.warning("Failed to sync CompanyAlias DB: %s", e)

                        form.save()
                        _sync_company_operating_cities(
                            selected_company, operating_cities_text
                        )

                        # Return JSON for AJAX requests
                        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                        if is_ajax:
                            return JsonResponse({'success': True, 'message': 'Company details saved successfully.'})

                        messages.success(request, "✅ Company details saved.")
                        return redirect(f"/label_companies/?company={selected_company.id}")
                    else:
                        # Form validation failed
                        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                        if is_ajax:
                            errors = '; '.join([f"{field}: {', '.join(errs)}" for field, errs in form.errors.items()])
                            return JsonResponse({'success': False, 'message': f'Validation errors: {errors}'})
                    # If invalid, fall through to render the bound form with errors
            else:
                # GET request: initialize form with current data, career URL and alias from companies.json
                form = CompanyEditForm(
                    instance=selected_company, initial={"career_url": career_url, "alias": alias}
                )

    # Handle new company creation mode (Quick Add prefill)
    if creating_new_company and not selected_company:
        def _create_company_from_bound_form(bound_form, operating_text):
            """Create a company from a validated/bound form and sync companies.json."""
            company_name = (bound_form.cleaned_data.get("name") or "").strip()
            if not company_name:
                messages.error(request, "❌ Please enter a company name before saving.")
                return None

            domain = (bound_form.cleaned_data.get("domain") or "").strip()
            homepage = (bound_form.cleaned_data.get("homepage") or "").strip()
            if not domain and not homepage:
                messages.error(
                    request,
                    "❌ Please enter at least a domain or homepage before saving.",
                )
                return None

            domain = _synchronized_domain(domain, homepage)

            new_company = bound_form.save(commit=False)
            new_company.domain = domain
            new_company.confidence = 1.0
            new_company.first_contact = now()
            new_company.last_contact = now()
            if not new_company.status:
                new_company.status = "new"
            new_company.save()
            _sync_company_operating_cities(new_company, operating_text)
            messages.success(request, f"✅ New Company: {new_company.name} added")

            career_url = (bound_form.cleaned_data.get("career_url") or "").strip()
            alias_input = (bound_form.cleaned_data.get("alias") or "").strip()

            # Register the new company in companies.json surgically
            try:
                reg_aliases = [a.strip() for a in alias_input.split(",") if a.strip()] if alias_input else None
                companies_store.register_company(
                    new_company.name,
                    domain=domain or None,
                    career_url=career_url or None,
                    aliases=reg_aliases,
                    source="companies.create_company",
                )
            except Exception as e:
                messages.warning(request, f"⚠️ Failed to register in companies.json: {e}")

            # Sync aliases to CompanyAlias DB table so they survive companies.json restores.
            try:
                from tracker.models import CompanyAlias as DBCompanyAlias
                if alias_input:
                    db_new_aliases = [a.strip() for a in alias_input.split(",") if a.strip()]
                    DBCompanyAlias.objects.filter(company=new_company.name).exclude(
                        alias__in=db_new_aliases
                    ).delete()
                    for db_alias in db_new_aliases:
                        DBCompanyAlias.objects.update_or_create(
                            alias=db_alias,
                            defaults={"company": new_company.name},
                        )
            except Exception as e:
                logger.warning("Failed to sync CompanyAlias DB for new company: %s", e)

            return new_company

        if request.method == "POST":
            # Debug: Log all POST data at the start
            logger.info(
                "NEW COMPANY POST received. Action=%s, POST keys=%s",
                request.POST.get("action"),
                list(request.POST.keys()),
            )

            # Handle populate action for new company
            if request.POST.get("action") == "populate_from_homepage":
                homepage_url = request.POST.get("homepage", "").strip()
                operating_cities_text = request.POST.get("operating_cities_text", "")
                if not homepage_url:
                    messages.error(request, "❌ Please enter a homepage URL first.")
                    form = CompanyEditForm(initial={"name": new_company_name})
                else:
                    form = CompanyEditForm(request.POST)
                    if form.is_valid():
                        new_company = _create_company_from_bound_form(
                            form, operating_cities_text
                        )
                        if new_company:
                            messages.info(
                                request,
                                "ℹ️ Company created. Running Populate on the saved record...",
                            )
                            return redirect(
                                f"/label_companies/?company={new_company.id}&auto_populate=1"
                            )
                    else:
                        error_messages = []
                        for field, errors in form.errors.items():
                            for error in errors:
                                error_messages.append(f"{field}: {error}")
                        messages.error(
                            request,
                            "❌ Please fix the following errors before populating: "
                            + "; ".join(error_messages),
                        )
            # Handle create action
            elif request.POST.get("action") == "create_new_company":
                # User submitted the new company form
                form = CompanyEditForm(request.POST)
                operating_cities_text = request.POST.get("operating_cities_text", "")

                # Debug logging
                logger.info(
                    "Create company form submitted. POST data: %s",
                    dict(request.POST),
                )
                logger.info(f"Form is_valid: {form.is_valid()}")
                if not form.is_valid():
                    logger.error(f"Form errors: {form.errors}")

                if form.is_valid():
                    new_company = _create_company_from_bound_form(
                        form, operating_cities_text
                    )
                    if new_company:
                        return redirect(f"/label_companies/?company={new_company.id}")
                else:
                    # Form validation failed - show errors
                    error_messages = []
                    for field, errors in form.errors.items():
                        for error in errors:
                            error_messages.append(f"{field}: {error}")
                    messages.error(request, f"❌ Please fix the following errors: {'; '.join(error_messages)}")
                # If form invalid, it stays bound with errors for re-display
        else:
            # GET request: show form with prefilled scraped data
            initial_data = {}
            if new_company_name:
                initial_data["name"] = new_company_name
            if prefill_homepage:
                initial_data["homepage"] = prefill_homepage
            if prefill_domain:
                initial_data["domain"] = prefill_domain
            if prefill_career_url:
                initial_data["career_url"] = prefill_career_url
            if prefill_notes:
                initial_data["notes"] = prefill_notes
            form = CompanyEditForm(initial=initial_data)

    ctx = build_sidebar_context()

    # Get all application threads for selected company (for Application Details section)
    # Include threads where ANY message has job_application label, not just thread-level label
    # This ensures we capture threads that started as applications but later got interview/rejection msgs
    # Also include ThreadTracking records created with msg_id as thread_id (for multiple
    # applications on the same Gmail thread—e.g., identical ATS subjects grouped by Gmail)
    application_threads = []
    if selected_company:
        from django.db.models import Q
        app_messages = Message.objects.filter(
            company=selected_company,
            ml_label='job_application'
        )
        application_thread_ids = set(
            app_messages.values_list('thread_id', flat=True).distinct()
        )
        application_msg_ids = set(
            app_messages.values_list('msg_id', flat=True).distinct()
        )
        # TTs can be keyed by either Gmail thread_id or individual msg_id
        all_tt_lookup_ids = application_thread_ids | application_msg_ids

        application_threads = list(ThreadTracking.objects.filter(
            Q(company=selected_company) & Q(thread_id__in=all_tt_lookup_ids)
        ).order_by('-sent_date'))

    # Get company documents
    company_documents = []
    if selected_company:
        company_documents = list(selected_company.documents.all())

    # Get defense contracts linked to this company
    company_contracts = []
    total_contract_amount = 0
    if selected_company:
        from django.db.models import Sum
        contracts_qs = selected_company.defense_contracts.all()
        # Calculate total amount
        agg = contracts_qs.aggregate(total=Sum('amount'))
        total_contract_amount = agg['total'] or 0
        company_contracts = list(
            selected_company.defense_contracts.order_by("-article_date")[:20]
        )

    # Get interaction records for selected company
    company_interactions = []
    if selected_company:
        from tracker.models import CompanyInteraction
        company_interactions = list(
            CompanyInteraction.objects.filter(company=selected_company).order_by("-interaction_date")
        )

    homepage_domain = _extract_homepage_domain(
        getattr(selected_company, "homepage", "") if selected_company else ""
    )

    # News is loaded asynchronously via AJAX after page render (see get_company_news endpoint)
    # We only pass whether a company is selected so the template can render the placeholder
    company_news = None
    news_error = None

    ctx.update(
        {
            "company_list": companies,
            "selected_company": selected_company,
            "form": form,
            "latest_label": latest_label,
            "last_message_ts": last_message_ts,
            "days_since_last_message": days_since_last_message,
            "ghosted_days_threshold": ghosted_days_threshold,
            "message_count": message_count,
            "message_info_list": message_info_list,
            "operating_cities_text": operating_cities_text,
            "operating_cities_list": operating_cities_list,
            "creating_new_company": creating_new_company,
            "new_company_name": new_company_name,
            "application_threads": application_threads,
            "company_documents": company_documents,
            "company_contracts": company_contracts, # Renamed to match the variable populated above
            "contracts": company_contracts,         # Also map to 'contracts' for template usage
            "total_contract_amount": total_contract_amount,
            "company_news": company_news,
            "news_error": news_error,
            "company_interactions": company_interactions,
            "homepage_domain": homepage_domain,
        }
    )
    return render(request, "tracker/label_companies.html", ctx)


@login_required
def companies_in_city(request):
    """Search companies by city using fuzzy matching on HQ and additional cities."""
    search_city = (request.GET.get("city") or "").strip()
    search_city_normalized = _normalize_city_for_match(search_city)

    companies_qs = Company.objects.exclude(status="headhunter")
    matches = []

    if search_city:
        candidates = (
            companies_qs.distinct()
            .order_by(Lower("name"))
            .prefetch_related("operating_cities")
        )
        matches = [
            company
            for company in candidates
            if _company_matches_city(company, search_city_normalized)
        ]

    ctx = build_sidebar_context()
    ctx.update(
        {
            "search_city": search_city,
            "city_companies": matches,
            "result_count": len(matches) if search_city else 0,
        }
    )
    return render(request, "tracker/companies_in_city.html", ctx)


@login_required
def merge_companies(request):
    """Merge multiple companies: reassign all messages/applications to canonical company, delete duplicates."""
    """Merge multiple companies: reassign all messages/applications to canonical company, delete duplicates."""
    if request.method == "POST":
        company_ids = request.POST.getlist("company_ids")
        canonical_id = request.POST.get("canonical_id")

        if not company_ids or len(company_ids) < 2:
            messages.error(request, "⚠️ Please select at least 2 companies to merge.")
            return redirect("label_companies")

        if not canonical_id or canonical_id not in company_ids:
            messages.error(
                request, "⚠️ Please select which company is the canonical (real) name."
            )
            return redirect("label_companies")

        try:
            canonical_company = Company.objects.get(id=canonical_id)
            duplicate_ids = [cid for cid in company_ids if cid != canonical_id]
            duplicates = Company.objects.filter(id__in=duplicate_ids)

            # Reassign all messages
            messages_moved = Message.objects.filter(company__in=duplicates).update(
                company=canonical_company
            )
            # Reassign all applications
            apps_moved = ThreadTracking.objects.filter(company__in=duplicates).update(
                company=canonical_company
            )

            # Update canonical company timestamps if needed
            all_messages = Message.objects.filter(company=canonical_company).order_by(
                "timestamp"
            )
            if all_messages.exists():
                canonical_company.first_contact = all_messages.first().timestamp
                canonical_company.last_contact = all_messages.last().timestamp
                canonical_company.save()

            # Delete duplicate companies
            dup_names = list(duplicates.values_list("name", flat=True))
            duplicates.delete()

            messages.success(
                request,
                f"✅ Merged {len(dup_names)} companies into '{canonical_company.name}'. "
                f"Moved {messages_moved} messages and {apps_moved} applications. Deleted: {', '.join(dup_names)}.",
            )
        except Company.DoesNotExist:
            messages.error(request, "⚠️ Canonical company not found.")
        except Exception as e:
            messages.error(request, f"❌ Merge failed: {e}")

        return redirect("label_companies")

    # GET: show merge form with selected companies
    company_ids = request.GET.getlist("company_ids")
    if not company_ids or len(company_ids) < 2:
        messages.warning(
            request,
            "⚠️ Please select at least 2 companies to merge from the Label Companies page.",
        )
        return redirect("label_companies")

    companies_to_merge = Company.objects.filter(id__in=company_ids).order_by("name")
    ctx = {"companies_to_merge": companies_to_merge}
    return render(request, "tracker/merge_companies.html", ctx)


# Constants for manage_domains function
ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")


def manage_domains(request):
    """
    Domain management page for classifying email domains as personal, company, ATS, or headhunter.
    Extracts domains from ingested messages and allows bulk labeling.
    """
    from collections import Counter, defaultdict

    # Paths to JSON files
    companies_path = Path(__file__).parent.parent.parent / "json" / "companies.json"
    personal_domains_path = (
        Path(__file__).parent.parent.parent / "json" / "personal_domains.json"
    )

    # Load existing classifications
    companies_data = {}
    if companies_path.exists():
        with open(companies_path, "r", encoding="utf-8") as f:
            companies_data = json.load(f)

    personal_domains_data = {}
    if personal_domains_path.exists():
        with open(personal_domains_path, "r", encoding="utf-8") as f:
            personal_domains_data = json.load(f)

    domain_to_company = companies_data.get("domain_to_company", {})
    ats_domains = set(companies_data.get("ats_domains", []))
    headhunter_domains = set(companies_data.get("headhunter_domains", []))
    job_boards = set(companies_data.get("job_boards", []))
    personal_domains = set(personal_domains_data.get("domains", []))

    # Debug: compute counts for Job Boards vs rendered list to investigate Issue #28
    try:
        job_board_domains_db = (
            Company.objects.filter(status="job_board", domain__isnull=False)
            .values_list("domain", flat=True)
            .distinct()
        )
        job_board_domains_db = set(job_board_domains_db)
    except Exception:
        job_board_domains_db = set()

    try:
        job_board_badge_count = len(job_boards) if isinstance(job_boards, set) else 0
    except Exception:
        job_board_badge_count = 0

    # Write a small debug log entry for comparison
    try:
        dbg_path = Path("logs") / "manage_domains_debug.log"
        dbg_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": now().isoformat(),
            "user": getattr(getattr(request, "user", None), "username", "unknown"),
            "job_board_badge_count": job_board_badge_count,
            "job_board_db_distinct": sorted(job_board_domains_db),
            "job_board_db_count": len(job_board_domains_db),
        }
        # Also print to console to confirm execution path
        print("[manage_domains debug]", entry)
        with open(dbg_path, "a", encoding="utf-8") as df:
            df.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Handle POST requests for labeling
    reingest_summary = None
    # Expose debug counts in context for immediate UI verification
    debug_counts = {
        "job_board_badge_count": job_board_badge_count,
        "job_board_db_count": len(job_board_domains_db),
    }

    if request.method == "POST":
        action = request.POST.get("action")
        label_type = request.POST.get("label_type")

        if action == "sync_db_to_json":
            # Sync Company domains from database to companies.json
            try:
                synced_domains = 0
                synced_ats = 0

                # Get all companies with domains from database
                companies_with_domains = Company.objects.filter(
                    domain__isnull=False
                ).exclude(domain="").select_related()

                # Define domains to skip (personal, receipts, etc.)
                skip_domains = {
                    "redditmail.com",
                    "dropbox.com",
                    "slack.com",
                    "stripe.com",
                    "clover.com",
                    "toasttab.com",
                    "invalidemail.com",
                    "indeed.com",
                    "ereceipt.usps.gov",
                    "govdelivery.dmv.virginia.gov",
                    "marketing.carmaxautofinance.com",
                    "info.wifionboard.com",
                    "estatement.apria.com",
                    "email.alaskaair.com",
                    "ops.sense.com",
                    "oracleheartva.com",
                    "osc.gov",
                    "peoplentech.com",
                    "rachelsfba.com",
                    "rmcweb.com",
                    "rokland.com",
                    "txn.getjobber.com",
                    "topsidefcu.org",
                    "virustotal.com",
                    "vec.virginia.gov",
                    "katorparks.com",
                    "jamhoff.com",
                    "app.slicelife.com",
                    "docusign.net",
                }

                _original_dtc = set(domain_to_company.keys())
                _original_ats = set(ats_domains)
                _original_headhunter = set(headhunter_domains)

                for company in companies_with_domains:
                    domain = company.domain.strip().lower()

                    # Skip if already in companies.json or in skip list
                    if domain in domain_to_company or domain in skip_domains:
                        continue

                    # Skip if it's already an ATS domain
                    if domain in ats_domains:
                        continue

                    # Check if company is a headhunter
                    if company.status == "headhunter":
                        if domain not in headhunter_domains:
                            headhunter_domains.add(domain)
                            synced_domains += 1
                    else:
                        # Add to domain_to_company
                        domain_to_company[domain] = company.name
                        synced_domains += 1

                    # Also sync ATS domain if present
                    if company.ats and company.ats.strip():
                        ats_domain = company.ats.strip().lower()
                        if ats_domain not in ats_domains:
                            ats_domains.add(ats_domain)
                            synced_ats += 1

                # Save updated companies.json
                companies_store.merge_domain_mappings(
                    {d: n for d, n in domain_to_company.items() if d not in _original_dtc},
                    ats_domains - _original_ats,
                    headhunter_domains - _original_headhunter,
                    source="companies.sync_domains",
                )

                messages.success(
                    request,
                    f"✅ Synced {synced_domains} company domain(s) and "
                    f"{synced_ats} ATS domain(s) from database to companies.json",
                )
                return redirect("manage_domains")

            except Exception as e:
                messages.error(request, f"❌ Error syncing domains: {e}")
                logger.exception("Domain sync error")

        elif action == "reingest_domains":
            # Re-ingest messages from specific domains
            reingest_filter = request.POST.get("reingest_filter", "personal")
            selected_domains = request.POST.getlist("domains")

            # Determine which domains to re-ingest
            domains_to_reingest = set()
            if reingest_filter == "personal":
                domains_to_reingest = personal_domains.copy()
            elif reingest_filter == "selected":
                domains_to_reingest = set(selected_domains)
            elif reingest_filter == "current_filter":
                # Re-ingest domains from the current filter view
                current_filter_param = request.POST.get("current_filter", "unlabeled")
                search_param = request.POST.get("search_query", "").strip().lower()

                # Get all domains from messages
                messages_qs = Message.objects.all()
                domain_counter = Counter()
                for msg in messages_qs.values("sender"):
                    sender = msg["sender"]
                    if "@" in sender:
                        email = sender
                        if "<" in sender and ">" in sender:
                            import re

                            email_matches = re.findall(r"<([^>]+@[^>]+)>", sender)
                            if email_matches:
                                email = email_matches[-1]
                        if "@" in email:
                            domain = email.split("@")[-1].lower()
                            if domain != "manual" and not domain.startswith("manual_"):
                                domain_counter[domain] += 1

                # Apply filter
                all_domain_list = list(domain_counter.keys())
                filtered_domains = []

                for domain in all_domain_list:
                    # Apply search filter
                    if search_param and search_param not in domain.lower():
                        continue

                    # Apply category filter
                    if current_filter_param == "unlabeled":
                        if (
                            domain not in personal_domains
                            and domain not in ats_domains
                            and domain not in headhunter_domains
                            and domain not in job_boards
                            and domain not in domain_to_company
                        ):
                            filtered_domains.append(domain)
                    elif (
                        current_filter_param == "personal"
                        and domain in personal_domains
                    ):
                        filtered_domains.append(domain)
                    elif (
                        current_filter_param == "company"
                        and domain in domain_to_company
                    ):
                        filtered_domains.append(domain)
                    elif current_filter_param == "ats" and domain in ats_domains:
                        filtered_domains.append(domain)
                    elif (
                        current_filter_param == "headhunter"
                        and domain in headhunter_domains
                    ):
                        filtered_domains.append(domain)
                    elif current_filter_param == "job_boards" and domain in job_boards:
                        filtered_domains.append(domain)
                    elif current_filter_param == "all":
                        filtered_domains.append(domain)

                domains_to_reingest = set(filtered_domains)
            elif reingest_filter == "all_labeled":
                domains_to_reingest = personal_domains | ats_domains
                domains_to_reingest |= headhunter_domains | job_boards
                domains_to_reingest |= set(domain_to_company.keys())

            if not domains_to_reingest:
                messages.warning(request, "⚠️ No domains selected for re-ingestion.")
            else:
                try:
                    from gmail_auth import get_gmail_service

                    ingest_message = _get_parser_module().ingest_message
                    service = get_gmail_service()
                    if not service:
                        messages.error(
                            request, "❌ Failed to initialize Gmail service."
                        )
                    else:
                        # Find all messages from these domains
                        messages_to_reingest = []
                        for msg in Message.objects.all().values(
                            "msg_id", "sender", "subject", "ml_label"
                        ):
                            sender = msg["sender"]
                            if "@" in sender:
                                email = sender
                                if "<" in sender and ">" in sender:
                                    email = sender[
                                        sender.index("<") + 1 : sender.index(">")
                                    ]
                                domain = email.split("@")[-1].lower()

                                if domain in domains_to_reingest:
                                    messages_to_reingest.append(
                                        {
                                            "msg_id": msg["msg_id"],
                                            "subject": msg["subject"],
                                            "domain": domain,
                                            "old_label": msg["ml_label"],
                                        }
                                    )

                        # Re-ingest messages
                        processed = 0
                        updated_to_noise = 0
                        kept_as_other = 0
                        errors = 0
                        sample_updates = []

                        for msg_info in messages_to_reingest[
                            :1000
                        ]:  # Limit to 1000 to avoid timeout
                            try:
                                old_label = msg_info["old_label"]
                                ingest_message(service, msg_info["msg_id"])

                                # Check new label
                                updated_msg = Message.objects.get(
                                    msg_id=msg_info["msg_id"]
                                )
                                new_label = updated_msg.ml_label

                                processed += 1

                                if new_label == "noise" and old_label != "noise":
                                    updated_to_noise += 1
                                    if len(sample_updates) < 5:
                                        sample_updates.append(
                                            f"{msg_info['subject'][:50]} ({msg_info['domain']}) → noise"
                                        )
                                elif new_label == "other":
                                    kept_as_other += 1
                            except Exception as e:
                                errors += 1
                                logger.error(
                                    f"Error re-ingesting {msg_info['msg_id']}: {e}"
                                )

                        reingest_summary = {
                            "domains_processed": len(domains_to_reingest),
                            "messages_processed": processed,
                            "updated_to_noise": updated_to_noise,
                            "kept_as_other": kept_as_other,
                            "errors": errors,
                            "sample_updates": sample_updates,
                        }

                        messages.success(
                            request,
                            f"✅ Re-ingested {processed} messages from {len(domains_to_reingest)} domain(s). "
                            f"{updated_to_noise} updated to noise.",
                        )
                except Exception as e:
                    messages.error(request, f"⚠️ Error during re-ingestion: {e}")
                    logger.exception("Re-ingestion error")

        elif action == "bulk_label":
            domains = request.POST.getlist("domains")
            if not domains:
                messages.error(request, "⚠️ No domains selected.")
            elif not label_type:
                messages.error(request, "⚠️ No label type specified.")
            else:
                try:
                    # Remove from all categories first
                    for domain in domains:
                        personal_domains.discard(domain)
                        ats_domains.discard(domain)
                        headhunter_domains.discard(domain)
                        job_boards.discard(domain)
                        if domain in domain_to_company:
                            del domain_to_company[domain]

                    # Add to selected category
                    if label_type == "personal":
                        personal_domains.update(domains)
                    elif label_type == "ats":
                        ats_domains.update(domains)
                    elif label_type == "headhunter":
                        headhunter_domains.update(domains)
                    elif label_type == "job_boards":
                        job_boards.update(domains)
                    elif label_type == "company":
                        # Extract company from existing Message records for this domain
                        import re
                        from email.utils import parseaddr

                        for domain in domains:
                            if domain not in domain_to_company:
                                company_name = None

                                # Check if this is an ATS domain (e.g., otp.workday.com)
                                # ATS domains serve multiple companies and should not be labeled as "company"
                                is_ats = False
                                domain_lower = domain.lower()
                                for ats_root in ats_domains:
                                    if (
                                        domain_lower == ats_root
                                        or domain_lower.endswith(f".{ats_root}")
                                    ):
                                        is_ats = True
                                        break

                                if is_ats:
                                    # Don't label ATS domains as company - warn the user
                                    messages.warning(
                                        request,
                                        f"⚠️ {domain} appears to be an ATS domain (serves multiple companies). "
                                        f"Consider labeling it as 'ATS' instead.",
                                    )
                                    continue

                                # First, check if messages from this domain already have a company assigned
                                domain_messages = Message.objects.filter(
                                    sender__icontains=f"@{domain}",
                                    company__isnull=False,
                                ).select_related("company")[:5]

                                if domain_messages:
                                    # Check if multiple companies use this domain
                                    from collections import Counter

                                    companies = [
                                        msg.company.name
                                        for msg in domain_messages
                                        if msg.company
                                    ]
                                    if companies:
                                        company_counts = Counter(companies)
                                        # If more than one company with significant representation, it's likely an ATS
                                        if (
                                            len(company_counts) > 1
                                            and company_counts.most_common(2)[1][1] > 1
                                        ):
                                            messages.warning(
                                                request,
                                                f"⚠️ {domain} is used by multiple "
                                                f"companies ({', '.join(company_counts.keys())}). "
                                                "This may be an ATS domain. Consider "
                                                "labeling it as 'ATS' instead.",
                                            )
                                            continue
                                        company_name = company_counts.most_common(1)[0][
                                            0
                                        ]

                                # Fallback: Parse from sender display name
                                if not company_name:
                                    sender_messages = Message.objects.filter(
                                        sender__icontains=f"@{domain}"
                                    ).values("sender")[:5]
                                    for msg in sender_messages:
                                        sender = msg["sender"]
                                        # Extract display name from "Display Name <email@domain.com>"
                                        display_name, _ = parseaddr(sender)
                                        if display_name:
                                            # Clean up common suffixes
                                            cleaned = re.sub(
                                                (
                                                    r"\s*(Talent|Careers?|Jobs?|"
                                                    r"Recruiting|HR|Notifications?|"
                                                    r"Team|Hiring|Acquisition)\s*$"
                                                ),
                                                "",
                                                display_name,
                                                flags=re.IGNORECASE,
                                            ).strip()
                                            if cleaned and len(cleaned) > 2:
                                                company_name = cleaned
                                                break

                                # Final fallback: use the main domain name (not subdomain)
                                if not company_name:
                                    parts = domain.split(".")
                                    if len(parts) >= 2:
                                        # Use the second-to-last part (e.g., "brassring" from "trm.brassring.com")
                                        company_name = parts[-2].title()
                                    else:
                                        company_name = parts[0].title()

                                domain_to_company[domain] = company_name

                    # Save to JSON files
                    personal_domains_data["domains"] = sorted(personal_domains)
                    with open(personal_domains_path, "w", encoding="utf-8") as f:
                        json.dump(
                            personal_domains_data, f, indent=2, ensure_ascii=False
                        )

                    _domain_labels = []
                    for _d in domains:
                        if _d in domain_to_company:
                            _domain_labels.append(
                                {
                                    "domain": _d,
                                    "label_type": "company",
                                    "company_name": domain_to_company[_d],
                                }
                            )
                        elif _d in ats_domains:
                            _domain_labels.append({"domain": _d, "label_type": "ats"})
                        elif _d in headhunter_domains:
                            _domain_labels.append({"domain": _d, "label_type": "headhunter"})
                        elif _d in job_boards:
                            _domain_labels.append({"domain": _d, "label_type": "job_board"})
                        else:
                            # Removed from all categories (skipped or personal)
                            _domain_labels.append({"domain": _d, "label_type": "personal"})
                    companies_store.apply_domain_classifications(
                        _domain_labels, source="companies.bulk_label"
                    )

                    messages.success(
                        request, f"✅ Labeled {len(domains)} domain(s) as {label_type}."
                    )
                    return redirect("manage_domains")
                except Exception as e:
                    messages.error(request, f"⚠️ Error saving domain labels: {e}")

        elif action == "label_single":
            domain = request.POST.get("domain")
            if domain and label_type:
                try:
                    # Remove from all categories first
                    personal_domains.discard(domain)
                    ats_domains.discard(domain)
                    headhunter_domains.discard(domain)
                    job_boards.discard(domain)
                    if domain in domain_to_company:
                        del domain_to_company[domain]

                    # Add to selected category
                    if label_type == "personal":
                        personal_domains.add(domain)
                    elif label_type == "ats":
                        ats_domains.add(domain)
                    elif label_type == "headhunter":
                        headhunter_domains.add(domain)
                    elif label_type == "job_boards":
                        job_boards.add(domain)
                    elif label_type == "company":
                        # Extract company from existing Message records for this domain
                        import re
                        from email.utils import parseaddr

                        company_name = None

                        # Check if this is an ATS domain (e.g., otp.workday.com)
                        # ATS domains serve multiple companies and should not be labeled as "company"
                        is_ats = False
                        domain_lower = domain.lower()
                        for ats_root in ats_domains:
                            if domain_lower == ats_root or domain_lower.endswith(
                                f".{ats_root}"
                            ):
                                is_ats = True
                                break

                        if is_ats:
                            # Don't label ATS domains as company - warn the user
                            messages.warning(
                                request,
                                f"⚠️ {domain} appears to be an ATS domain (serves multiple companies). "
                                f"Consider labeling it as 'ATS' instead.",
                            )
                            return redirect(
                                f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                            )

                        # First, check if messages from this domain already have a company assigned
                        domain_messages = Message.objects.filter(
                            sender__icontains=f"@{domain}", company__isnull=False
                        ).select_related("company")[:5]

                        if domain_messages:
                            # Check if multiple companies use this domain
                            from collections import Counter

                            companies = [
                                msg.company.name
                                for msg in domain_messages
                                if msg.company
                            ]
                            if companies:
                                company_counts = Counter(companies)
                                # If more than one company with significant representation, it's likely an ATS
                                if (
                                    len(company_counts) > 1
                                    and company_counts.most_common(2)[1][1] > 1
                                ):
                                    messages.warning(
                                        request,
                                        f"⚠️ {domain} is used by multiple companies "
                                        f"({', '.join(company_counts.keys())}). "
                                        "This may be an ATS domain. Consider labeling "
                                        "it as 'ATS' instead.",
                                    )
                                    return redirect(
                                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                                    )
                                company_name = company_counts.most_common(1)[0][0]

                        # Fallback: Parse from sender display name
                        if not company_name:
                            sender_messages = Message.objects.filter(
                                sender__icontains=f"@{domain}"
                            ).values("sender")[:5]
                            for msg in sender_messages:
                                sender = msg["sender"]
                                # Extract display name from "Display Name <email@domain.com>"
                                display_name, _ = parseaddr(sender)
                                if display_name:
                                    # Clean up common suffixes
                                    cleaned = re.sub(
                                        (
                                            r"\s*(Talent|Careers?|Jobs?|Recruiting|"
                                            r"HR|Notifications?|Team|Hiring|"
                                            r"Acquisition)\s*$"
                                        ),
                                        "",
                                        display_name,
                                        flags=re.IGNORECASE,
                                    ).strip()
                                    if cleaned and len(cleaned) > 2:
                                        company_name = cleaned
                                        break

                        # Final fallback: use the main domain name (not subdomain)
                        if not company_name:
                            parts = domain.split(".")
                            if len(parts) >= 2:
                                # Use the second-to-last part (e.g., "brassring" from "trm.brassring.com")
                                company_name = parts[-2].title()
                            else:
                                company_name = parts[0].title()

                        domain_to_company[domain] = company_name

                    # Save to JSON files
                    personal_domains_data["domains"] = sorted(personal_domains)
                    with open(personal_domains_path, "w", encoding="utf-8") as f:
                        json.dump(
                            personal_domains_data, f, indent=2, ensure_ascii=False
                        )

                    companies_store.classify_domain(
                        domain,
                        label_type,
                        domain_to_company.get(domain),
                        source="companies.label_single",
                    )

                    messages.success(request, f"✅ Labeled {domain} as {label_type}.")
                    return redirect(
                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                    )
                except Exception as e:
                    messages.error(request, f"⚠️ Error saving domain label: {e}")
                    logger.exception("Error in label_single")
                    return redirect(
                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                    )

    # Reload JSON data to ensure we have the latest classifications
    # (Important after POST operations that modify the files)
    if companies_path.exists():
        with open(companies_path, "r", encoding="utf-8") as f:
            companies_data = json.load(f)
    if personal_domains_path.exists():
        with open(personal_domains_path, "r", encoding="utf-8") as f:
            personal_domains_data = json.load(f)

    domain_to_company = companies_data.get("domain_to_company", {})
    ats_domains = set(companies_data.get("ats_domains", []))
    headhunter_domains = set(companies_data.get("headhunter_domains", []))
    job_boards = set(companies_data.get("job_boards", []))
    personal_domains = set(personal_domains_data.get("domains", []))

    # Extract all sender domains from messages
    messages_qs = Message.objects.all()
    domain_counter = Counter()
    domain_senders = defaultdict(list)

    for msg in messages_qs.values("sender"):
        sender = msg["sender"]
        if "@" in sender:
            # Parse email from "Name <email@domain.com>" or "email@domain.com"
            email = sender
            if "<" in sender and ">" in sender:
                # Find the last <...> that contains an @ symbol
                import re

                email_matches = re.findall(r"<([^>]+@[^>]+)>", sender)
                if email_matches:
                    email = email_matches[-1]  # Use the last match
                else:
                    # Fallback to original logic if regex fails
                    email = sender[sender.rindex("<") + 1 : sender.rindex(">")]

            # Only process if email contains @
            if "@" in email:
                domain = email.split("@")[-1].lower()

                # Skip placeholder domains from manual entries
                if domain == "manual" or domain.startswith("manual_"):
                    continue

                domain_counter[domain] += 1

                # Store sample senders (limit to 3)
                if len(domain_senders[domain]) < 3:
                    domain_senders[domain].append(sender[:50])

    # Build domain info list
    domains_info = []
    for domain, count in domain_counter.items():
        # Determine current label
        label = None
        company_name = None

        if domain in personal_domains:
            label = "personal"
        elif domain in ats_domains:
            label = "ats"
        elif domain in headhunter_domains:
            label = "headhunter"
        elif domain in job_boards:
            label = "job_boards"
        elif domain in domain_to_company:
            label = "company"
            company_name = domain_to_company[domain]

        domains_info.append(
            {
                "domain": domain,
                "count": count,
                "label": label,
                "company_name": company_name,
                "sample_senders": domain_senders[domain],
            }
        )

    # Filter based on query parameter
    current_filter = request.GET.get("filter", "unlabeled")
    search_query = request.GET.get("search", "").strip().lower()
    sort_by = request.GET.get("sort", "domain")  # domain, count, label
    sort_order = request.GET.get("order", "asc")  # asc, desc

    # Apply search filter
    if search_query:
        domains_info = [d for d in domains_info if search_query in d["domain"].lower()]

    # Apply category filter
    if current_filter == "unlabeled":
        domains_info = [d for d in domains_info if d["label"] is None]
    elif current_filter == "personal":
        domains_info = [d for d in domains_info if d["label"] == "personal"]
    elif current_filter == "company":
        domains_info = [d for d in domains_info if d["label"] == "company"]
    elif current_filter == "ats":
        domains_info = [d for d in domains_info if d["label"] == "ats"]
    elif current_filter == "headhunter":
        domains_info = [d for d in domains_info if d["label"] == "headhunter"]
    elif current_filter == "job_boards":
        # Option A: Use job_boards from JSON as canonical source
        jb_set = set(job_boards)
        # Augment existing info with any missing job board domains (ensure visibility even if no messages yet)
        existing_domains = {d["domain"] for d in domains_info}
        for jb in jb_set:
            if jb not in existing_domains:
                domains_info.append(
                    {
                        "domain": jb,
                        "count": 0,
                        "label": "job_boards",
                        "company_name": None,
                        "sample_senders": [],
                    }
                )
        # Filter to job boards
        domains_info = [d for d in domains_info if d["label"] == "job_boards"]
    # "all" shows everything

    # Apply sorting
    if sort_by == "count":
        domains_info.sort(key=lambda d: d["count"], reverse=sort_order == "desc")
    elif sort_by == "label":

        def label_sort_key(d):
            label = d["label"] or "zzz_unlabeled"  # Push unlabeled to end
            return label

        domains_info.sort(key=label_sort_key, reverse=sort_order == "desc")
    else:  # sort_by == "domain" (default)
        # Sort alphabetically by full domain name
        domains_info.sort(
            key=lambda d: d["domain"].lower(), reverse=(sort_order == "desc")
        )

    # Calculate stats; align Job Boards badge to JSON canonical list
    all_domains = list(domain_counter.keys())
    stats = {
        "total": len(all_domains),
        "unlabeled": sum(
            1
            for d in all_domains
            if d not in personal_domains
            and d not in ats_domains
            and d not in headhunter_domains
            and d not in job_boards
            and d not in domain_to_company
        ),
        "personal": len(personal_domains),
        "company": len(domain_to_company),
        "ats": len(ats_domains),
        "headhunter": len(headhunter_domains),
        "job_boards": len(set(job_boards)),
    }

    ctx = {
        "domains": domains_info,
        "current_filter": current_filter,
        "stats": stats,
        "reingest_summary": reingest_summary,
        "search_query": search_query,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    # Include debug counts
    ctx["debug_counts"] = debug_counts
    return render(request, "tracker/manage_domains.html", ctx)


@login_required
def job_search_tracker(request):
    """
    Track manual job searches across all companies.

    Shows all known companies with their last search date.
    Allows users to mark companies as searched today.
    """
    if request.method == "POST":
        company_id = request.POST.get("company_id")
        if company_id:
            try:
                company = Company.objects.get(pk=company_id)
                if request.POST.get("searched"):
                    company.last_job_search_date = now()
                    company.save()
                    messages.success(
                        request,
                        "✅ Marked "
                        f"{company.name} as searched on "
                        f"{company.last_job_search_date.strftime('%Y-%m-%d %H:%M')}"
                    )
                return redirect("job_search_tracker")
            except Company.DoesNotExist:
                messages.error(request, "❌ Company not found")

    # Check for filter parameters
    show_new_only = request.GET.get('new_only', 'false').lower() == 'true'
    focus_area_filter = request.GET.get('focus_area', '').strip()
    location_filter = request.GET.get('location', '').strip()

    # Get all companies ordered by last search date (nulls last)
    companies = Company.objects.annotate(
        message_count=Count('message')
    )

    # Filter for companies added today if requested
    today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    if show_new_only:
        companies = companies.filter(first_contact__gte=today_start)

    # Filter by focus area if specified
    if focus_area_filter:
        companies = companies.filter(focus_area__icontains=focus_area_filter)

    # Filter by location: match Company.location OR any CompanyOperatingCity.city
    if location_filter:
        companies = companies.filter(
            Q(location__icontains=location_filter) |
            Q(operating_cities__city__icontains=location_filter)
        ).distinct()

    companies = companies.order_by(
        F('last_job_search_date').desc(nulls_last=True),
        'name'
    )

    # Load career URLs from companies.json JobSites
    companies_json_path = Path("json/companies.json")
    job_sites = {}
    try:
        if companies_json_path.exists():
            with open(companies_json_path, "r", encoding="utf-8") as f:
                companies_json_data = json.load(f)
                job_sites = companies_json_data.get("JobSites", {})
    except Exception:
        pass

    # Attach career URLs to companies
    companies_with_urls = []
    for company in companies:
        company.career_url = job_sites.get(company.name, "")
        companies_with_urls.append(company)

    # Calculate stats
    total_companies = len(companies_with_urls)
    searched_companies = sum(1 for c in companies_with_urls if c.last_job_search_date)
    never_searched = total_companies - searched_companies

    # Get companies added today
    new_today = Company.objects.filter(first_contact__gte=today_start).count()

    # Get companies searched today
    searched_today = sum(
        1
        for c in companies_with_urls
        if c.last_job_search_date and c.last_job_search_date >= today_start
    )

    # Get companies searched in last 7 days
    week_ago = now() - timedelta(days=7)
    searched_this_week = sum(
        1
        for c in companies_with_urls
        if c.last_job_search_date and c.last_job_search_date >= week_ago
    )

    # Get companies searched in last 30 days
    month_ago = now() - timedelta(days=30)
    searched_this_month = sum(
        1
        for c in companies_with_urls
        if c.last_job_search_date and c.last_job_search_date >= month_ago
    )

    ctx = {
        **build_sidebar_context(),
        "companies_list": companies_with_urls,
        "total_companies": total_companies,
        "searched_companies": searched_companies,
        "never_searched": never_searched,
        "new_today": new_today,
        "searched_today": searched_today,
        "searched_this_week": searched_this_week,
        "searched_this_month": searched_this_month,
        "show_new_only": show_new_only,
        "focus_area_filter": focus_area_filter,
        "location_filter": location_filter,
    }

    return render(request, "tracker/job_search_tracker.html", ctx)

def _extract_job_posting_text_from_html(html_content):
    """Extract the most relevant job posting text from raw HTML."""
    from bs4 import BeautifulSoup
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning, module="bs4")

    soup = BeautifulSoup(html_content or "", "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
        element.decompose()

    main_content = None
    content_selectors = [
        ".BambooHR-ATS-board",
        ".BambooHR-ATS-Description",
        "[data-qa='job-description']",
        ".job-board__description",
        "#jobDescription",
        ".careers-description",
        "main",
        "article",
        "[role='main']",
        ".job-description",
        ".job-details",
        ".job-content",
        ".posting-description",
        "#job-description",
        "#job-details",
        ".description",
        ".content",
        ".main-content",
        "[class*='description']",
        "[class*='job-posting']",
        "[class*='posting-content']",
    ]

    for selector in content_selectors:
        main_content = soup.select_one(selector)
        if main_content:
            logger.info("scrape_job_posting: Found content using selector: %s", selector)
            break

    if not main_content:
        logger.warning("scrape_job_posting: No main content selector matched, trying fallback methods")
        divs = soup.find_all(["div", "section", "article"])
        if divs:
            main_content = max(divs, key=lambda d: len(d.get_text(strip=True)))
            logger.info("scrape_job_posting: Using largest text container as fallback")

    if not main_content:
        main_content = soup.body
        logger.warning("scrape_job_posting: Using body as last resort")

    if not main_content:
        return ""

    text = main_content.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def _scrape_job_posting_content(url: str, timeout: int = 15, allow_browser_fallback: bool = True):
    """Scrape a job posting with static-first fetching and rendered fallback."""
    timeout_ms = max(int(timeout * 1000), 1000)
    page_result = fetch_best_effort_page(
        url,
        timeout=timeout_ms,
        browser_first=should_use_browser_first(url),
        capture_json=True,
    )

    if not page_result["success"]:
        return {
            "success": False,
            "content": "",
            "error": page_result["error"] or "Failed to scrape page.",
            "status_code": page_result.get("status_code") or 500,
            "source_method": page_result.get("source_method"),
            "resolved_url": page_result.get("final_url") or url,
            "extracted_location": None,
        }

    text = _extract_job_posting_text_from_html(page_result["html"])
    if (
        allow_browser_fallback
        and page_result.get("source_method") == "static"
        and should_fallback_to_browser(url, text, page_result.get("status_code"))
    ):
        rendered_result = fetch_rendered_page(
            url,
            timeout=timeout_ms,
            capture_json=True,
        )
        if rendered_result["success"]:
            page_result = rendered_result
            text = _extract_job_posting_text_from_html(page_result["html"])

    if len(text) < 100:
        logger.warning("scrape_job_posting: Very little content extracted (%s chars)", len(text))
        debug_file = "/tmp/scrape_debug.html"
        try:
            with open(debug_file, "w", encoding="utf-8") as file_handle:
                file_handle.write(page_result["html"])
            logger.info("scrape_job_posting: Saved HTML to %s for debugging", debug_file)
        except Exception as exc:
            logger.error("scrape_job_posting: Failed to save debug HTML: %s", exc)

    if len(text) > 20000:
        text = text[:20000] + "\n\n[Content truncated to 20,000 characters]"

    locations = _extract_locations_from_html(page_result["html"])

    if len(text) < 50:
        return {
            "success": False,
            "content": "",
            "error": (
                "Could not extract meaningful content. The page may use "
                "JavaScript to load content. Try copying the text manually."
            ),
            "status_code": 200,
            "source_method": page_result.get("source_method"),
            "resolved_url": page_result.get("final_url") or url,
            "extracted_location": locations[0] if locations else None,
        }

    return {
        "success": True,
        "content": text,
        "error": None,
        "status_code": 200,
        "source_method": page_result.get("source_method"),
        "resolved_url": page_result.get("final_url") or url,
        "extracted_location": locations[0] if locations else None,
    }


@login_required
def scrape_job_posting(request):
    """
    AJAX endpoint to scrape job posting content from a URL.
    Returns the extracted text content as JSON.
    """
    if request.method != "POST":
        logger.warning(f"scrape_job_posting: Invalid method {request.method}")
        return JsonResponse({"error": "POST method required"}, status=405)

    url = request.POST.get("url", "").strip()
    logger.info(f"scrape_job_posting: Received URL: {url}")

    if not url:
        logger.warning("scrape_job_posting: No URL provided")
        return JsonResponse({"error": "URL is required"}, status=400)

    # Validate URL format
    if not url.startswith(("http://", "https://")):
        logger.warning(f"scrape_job_posting: Invalid URL format: {url}")
        return JsonResponse({"error": "URL must start with http:// or https://"}, status=400)

    try:
        logger.info("scrape_job_posting: Fetching URL: %s", url)
        result = _scrape_job_posting_content(url)
        status_code = result.pop("status_code", 200)
        return JsonResponse(result, status=status_code)
    except Exception as e:
        logger.exception("Failed to scrape job posting")
        return JsonResponse({"error": f"Failed to scrape page: {str(e)}"}, status=500)


@login_required
def missing_applications(request):
    """
    Find companies with rejections but fewer (or no) application confirmations.

    This helps identify cases where:
    - A rejection was received but no application confirmation email was tracked
    - More rejections exist than applications (multiple roles applied, only some confirmations received)
    """
    from django.db.models import Count, Q

    # Get companies with their application and rejection counts
    companies_with_counts = Company.objects.annotate(
        application_count=Count(
            'message',
            filter=Q(message__ml_label='job_application')
        ),
        rejection_count=Count(
            'message',
            filter=Q(message__ml_label='rejection')
        ),
        interview_count=Count(
            'message',
            filter=Q(message__ml_label='interview_invite')
        ),
    ).filter(
        rejection_count__gt=0  # Only companies with at least one rejection
    ).filter(
        rejection_count__gt=F('application_count')  # More rejections than applications
    ).order_by('-rejection_count', 'name')

    # Build detailed data for template
    companies_data = []
    for company in companies_with_counts:
        # Get the actual messages for context
        rejections = Message.objects.filter(
            company=company,
            ml_label='rejection'
        ).order_by('-timestamp')[:5]

        applications = Message.objects.filter(
            company=company,
            ml_label='job_application'
        ).order_by('-timestamp')[:5]

        missing_count = company.rejection_count - company.application_count

        companies_data.append({
            'company': company,
            'application_count': company.application_count,
            'rejection_count': company.rejection_count,
            'interview_count': company.interview_count,
            'missing_count': missing_count,
            'rejections': rejections,
            'applications': applications,
        })

    # Calculate summary stats
    total_missing = sum(c['missing_count'] for c in companies_data)
    total_companies_affected = len(companies_data)

    ctx = {
        **build_sidebar_context(),
        'companies_data': companies_data,
        'total_missing': total_missing,
        'total_companies_affected': total_companies_affected,
    }

    return render(request, 'tracker/missing_applications.html', ctx)


@login_required
def upload_company_document(request, company_id):
    """Upload a document to a company profile."""
    from tracker.models import Company, CompanyDocument

    company = get_object_or_404(Company, id=company_id)

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect(f"/label_companies/?company={company_id}")

    if "document" not in request.FILES:
        messages.error(request, "No file was uploaded.")
        return redirect(f"/label_companies/?company={company_id}")

    uploaded_file = request.FILES["document"]
    description = request.POST.get("description", "").strip()

    # Create the document record
    try:
        doc = CompanyDocument(
            company=company,
            file=uploaded_file,
            description=description
        )
        doc.full_clean()  # Run validators
        doc.save()
        messages.success(request, f"✅ Document '{doc.filename}' uploaded successfully.")
    except Exception as e:
        messages.error(request, f"❌ Failed to upload document: {str(e)}")

    return redirect(f"/label_companies/?company={company_id}")


@login_required
def delete_company_document(request, document_id):
    """Delete a document from a company profile."""
    from tracker.models import CompanyDocument

    doc = get_object_or_404(CompanyDocument, id=document_id)
    company_id = doc.company.id
    filename = doc.filename

    if request.method == "POST":
        # Delete the file from storage
        try:
            doc.file.delete(save=False)
        except Exception:
            pass  # File might not exist

        # Delete the database record
        doc.delete()
        messages.success(request, f"✅ Document '{filename}' deleted.")

    return redirect(f"/label_companies/?company={company_id}")


@login_required
def get_company_news(request, company_id):
    """GET endpoint to lazy-load company news after page render.

    Returns cached articles if fresh, otherwise fetches new ones.
    Called via AJAX on DOMContentLoaded to avoid blocking page load.
    """
    from tracker.models import Company, CompanyNews

    company = get_object_or_404(Company, id=company_id)
    force_refresh = request.GET.get('force') == '1'

    try:
        company_news, _ = CompanyNews.objects.get_or_create(company=company)

        # Fetch if cache is stale or force refresh requested
        if force_refresh or not company_news.is_cache_fresh():
            try:
                aggregator = NewsAggregator()
                articles = aggregator.get_news_for_company(
                    company.name,
                    num_articles=5,
                    days_back=30,
                    focus_area=getattr(company, "focus_area", None),
                    domain=getattr(company, "domain", None),
                )
                article_dicts = [article.to_dict() for article in articles]
                company_news.add_articles(article_dicts)
                company_news.last_fetched = now()
                company_news.error_message = ''
                company_news.save()
            except Exception as e:
                logger.warning(f"Failed to fetch news for {company.name}: {e}")
                company_news.error_message = str(e)
                company_news.save()
                hidden = set(company_news.hidden_urls or [])
                user_arts = [a for a in (company_news.user_articles or []) if a.get("url") not in hidden]
                display_arts = [a for a in (company_news.articles or []) if a.get("url") not in hidden]
                merged = sorted(
                    user_arts + display_arts,
                    key=lambda a: a.get("date") or "",
                    reverse=True,
                )
                return JsonResponse({
                    "success": True,
                    "articles": merged,
                    "all_articles": [a for a in (company_news.all_articles or []) if a.get("url") not in hidden],
                    "last_fetched": company_news.last_fetched.isoformat() if company_news.last_fetched else None,
                    "error": f"Could not fetch news: {str(e)[:100]}",
                })

        hidden = set(company_news.hidden_urls or [])
        user_arts = [a for a in (company_news.user_articles or []) if a.get("url") not in hidden]
        display_arts = [a for a in (company_news.articles or []) if a.get("url") not in hidden]
        merged = sorted(
            user_arts + display_arts,
            key=lambda a: a.get("date") or "",
            reverse=True,
        )
        return JsonResponse({
            "success": True,
            "articles": merged,
            "all_articles": [a for a in (company_news.all_articles or []) if a.get("url") not in hidden],
            "last_fetched": company_news.last_fetched.isoformat() if company_news.last_fetched else None,
            "error": None,
        })

    except Exception as e:
        logger.error(f"Error handling CompanyNews for {company.name}: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def refresh_company_news(request, company_id):
    """POST endpoint to force-refresh news for a company (Refresh button)."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)
    # Delegate to get_company_news with force=1
    request.GET = request.GET.copy()
    request.GET['force'] = '1'
    return get_company_news(request, company_id)


@login_required
@require_POST
def add_company_news_url(request, company_id):
    """Fetch a user-supplied URL and add it to the company's news list."""
    from bs4 import BeautifulSoup
    from django.utils.timezone import now as tz_now
    from tracker.models import Company, CompanyNews

    company = get_object_or_404(Company, pk=company_id)
    url = request.POST.get("url", "").strip()
    if not url:
        return JsonResponse({"error": "URL is required."}, status=400)

    from urllib.parse import urlparse

    # Derive a human-readable default title from the URL path
    parsed = urlparse(url)
    path_slug = (parsed.path.rstrip("/").split("/")[-1] or parsed.netloc).replace("-", " ").replace("_", " ")
    default_title = path_slug.capitalize() if path_slug else url
    source_domain = parsed.netloc or "user_added"

    title = default_title
    snippet = ""
    fetch_note = ""

    # Best-effort fetch — use curl_cffi to impersonate Chrome's TLS fingerprint,
    # which bypasses JA3-based bot detection (e.g. Cloudflare, Akamai) that rejects
    # the standard Python requests TLS stack regardless of HTTP headers.
    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(url, impersonate="chrome", timeout=15, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Prefer og:title > <title>
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.find("title"):
            title = soup.find("title").get_text(strip=True)

        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            snippet = og_desc["content"].strip()
        if not snippet:
            para = soup.find("p")
            snippet = para.get_text(strip=True)[:300] if para else ""
    except Exception as fetch_exc:
        fetch_note = f"(Could not fetch page: {fetch_exc})"
        logger.info("add_company_news_url: fetch failed for %s — %s", url, fetch_exc)

    article = {
        "title": (title or url)[:200],
        "url": url,
        "date": tz_now().isoformat(),
        "date_display": tz_now().strftime("%B %d, %Y"),
        "source": source_domain,
        "snippet": snippet or fetch_note,
        "user_added": True,
    }

    try:
        company_news, _ = CompanyNews.objects.get_or_create(company=company)
        user_articles = list(company_news.user_articles or [])
        if not any(a.get("url") == url for a in user_articles):
            user_articles.append(article)
        hidden = [u for u in (company_news.hidden_urls or []) if u != url]
        company_news.user_articles = user_articles
        company_news.hidden_urls = hidden
        company_news.save(update_fields=["user_articles", "hidden_urls"])
        return JsonResponse(article)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_POST
def remove_company_news_article(request, company_id):
    """Remove a news article by URL.

    User-added articles are hard-deleted from user_articles.
    Auto-scraped articles are soft-deleted into hidden_urls so the RSS
    fetcher doesn't re-surface them.
    """
    from tracker.models import Company, CompanyNews

    company = get_object_or_404(Company, pk=company_id)
    url = request.POST.get("url", "").strip()
    if not url:
        return JsonResponse({"error": "URL required."}, status=400)
    company_news, _ = CompanyNews.objects.get_or_create(company=company)

    user_articles = list(company_news.user_articles or [])
    was_user_added = any(a.get("url") == url for a in user_articles)

    if was_user_added:
        # Hard delete — permanently remove from the user's own list
        company_news.user_articles = [a for a in user_articles if a.get("url") != url]
        company_news.save(update_fields=["user_articles"])
        return JsonResponse({"status": "ok", "deleted": "hard"})
    else:
        # Soft delete — hide auto-scraped article so it won't reappear
        hidden = list(company_news.hidden_urls or [])
        if url not in hidden:
            hidden.append(url)
        company_news.hidden_urls = hidden
        company_news.save(update_fields=["hidden_urls"])
        return JsonResponse({"status": "ok", "deleted": "soft"})


@login_required
def add_company_interaction(request, company_id):
    """Add a new interaction record for a company."""
    from tracker.models import Company, CompanyInteraction
    from django.utils.dateparse import parse_datetime

    company = get_object_or_404(Company, pk=company_id)
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    contact_person = request.POST.get("contact_person", "").strip()
    if not contact_person:
        return JsonResponse({"error": "Contact person is required."}, status=400)

    is_phone = request.POST.get("is_phone") == "on"
    is_video = request.POST.get("is_video") == "on"
    is_text = request.POST.get("is_text") == "on"
    is_chat = request.POST.get("is_chat") == "on"
    if not any([is_phone, is_video, is_text, is_chat]):
        return JsonResponse({"error": "At least one interaction type must be selected."}, status=400)

    raw_date = request.POST.get("interaction_date", "").strip()
    interaction_date = parse_datetime(raw_date) if raw_date else now()
    if not interaction_date:
        return JsonResponse({"error": "Invalid date/time format."}, status=400)

    CompanyInteraction.objects.create(
        company=company,
        interaction_date=interaction_date,
        is_phone=is_phone,
        is_video=is_video,
        is_text=is_text,
        is_chat=is_chat,
        contact_person=contact_person,
        contact_phone=request.POST.get("contact_phone", "").strip() or None,
        contact_email=request.POST.get("contact_email", "").strip() or None,
        notes=request.POST.get("notes", "").strip() or None,
    )

    messages.success(request, f"✅ Interaction with {contact_person} saved.")
    return redirect(f"/label_companies/?company={company_id}")


@login_required
def delete_company_interaction(request, company_id, interaction_id):
    """Delete a company interaction record."""
    from tracker.models import CompanyInteraction

    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    interaction = get_object_or_404(CompanyInteraction, pk=interaction_id, company_id=company_id)
    interaction.delete()
    messages.success(request, "🗑️ Interaction deleted.")
    return redirect(f"/label_companies/?company={company_id}")


@login_required
def refresh_company_contracts(request, company_id):
    """Fetch/Refresh USASpending contracts for a specific company."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)

    try:
        company = get_object_or_404(Company, pk=company_id)
        service = USASpendingService()

        # We pass the company.name; the service normalizes it internally
        result = service.fetch_contracts_for_company(company.name)

        msg = f"Fetched {result['created']} new, {result['updated']} updated contracts."
        if result['errors'] > 0:
            msg += f" ({result['errors']} errors)"

        return JsonResponse({
            "status": "success",
            "message": msg,
            "data": result
        })
    except Exception as e:
        logger.error("Error refreshing contracts for company %s: %s", company_id, e)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@login_required
@require_POST
def extract_company_locations(request):
    """
    AJAX endpoint to extract locations from a provided URL or raw HTML.
    Returns a list of location strings in City, State format.
    """
    url = request.POST.get("url", "").strip()
    raw_html = request.POST.get("raw_html", "").strip()

    content = raw_html
    captured_json = []

    if not content and url:
        try:
            page_result = fetch_best_effort_page(
                url,
                timeout=15000,
                browser_first=should_use_browser_first(url),
                capture_json=True,
            )
            if not page_result["success"]:
                return JsonResponse({
                    "success": False,
                    "message": page_result.get("error") or "Failed to fetch the URL.",
                })
            content = page_result.get("html", "")
            captured_json = page_result.get("captured_json", [])
        except Exception as e:
            return JsonResponse({"success": False, "message": f"Failed to fetch the URL: {str(e)}. Try pasting the raw HTML instead."})

    if not content:
        return JsonResponse({"success": False, "message": "No URL or HTML content was provided."})

    try:
        locations = _extract_locations_from_html(content)
        if not locations and captured_json:
            locations = _extract_locations_from_captured_json(captured_json)
        if not locations:
            return JsonResponse({
                "success": False,
                "message": "No locations were found in the provided HTML/CSS/Javascript. The page might load its content dynamically or the format was not recognized."
            })
        return JsonResponse({"success": True, "locations": locations})
    except Exception as e:
        logger.exception("Error extracting locations")
        return JsonResponse({"success": False, "message": f"An error occurred while parsing the HTML: {str(e)}"})

__all__ = [
    "delete_company",
    "label_companies",
    "companies_in_city",
    "merge_companies",
    "manage_domains",
    "job_search_tracker",
    "scrape_job_posting",
    "missing_applications",
    "upload_company_document",
    "delete_company_document",
    "get_company_news",
    "refresh_company_news",
    "add_company_news_url",
    "remove_company_news_article",
    "add_company_interaction",
    "delete_company_interaction",
    "refresh_company_contracts",
    "extract_company_locations",
]
