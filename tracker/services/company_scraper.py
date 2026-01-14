"""
Company Homepage Scraper

Extracts company information from a company's homepage:
- Company name (from title, meta tags, or h1)
- Domain name (from URL)
- Career/Jobs page URL (from common link patterns)
"""

import re
from urllib.parse import urlparse, urljoin
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup


class CompanyScraperError(Exception):
    """Base exception for company scraper errors."""
    pass


def scrape_company_info(homepage_url: str, timeout: int = 10) -> Dict[str, str]:
    """
    Scrape company information from a homepage URL.
    
    Args:
        homepage_url: The company's homepage URL
        timeout: Request timeout in seconds (default: 10)
        
    Returns:
        Dictionary with keys:
        - name: Company name (extracted from page)
        - domain: Domain name (extracted from URL)
        - career_url: Career/Jobs page URL (if found, empty string if not found)
        
    Raises:
        CompanyScraperError: If scraping fails or URL is invalid
    """
    # Validate and normalize URL
    if not homepage_url:
        raise CompanyScraperError("Homepage URL is required")
    
    if not homepage_url.startswith(("http://", "https://")):
        homepage_url = "https://" + homepage_url
    
    try:
        parsed = urlparse(homepage_url)
        if not parsed.netloc:
            raise CompanyScraperError("Invalid URL format")
        domain = parsed.netloc.replace("www.", "")
    except Exception as e:
        raise CompanyScraperError(f"Invalid URL: {e}")
    
    # Fetch the page
    try:
        # Use minimal headers - more complex headers can trigger anti-bot measures
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(homepage_url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.Timeout:
        raise CompanyScraperError(f"Request timed out after {timeout} seconds. The website may be slow or unavailable.")
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            raise CompanyScraperError(f"Access denied (403 Forbidden). The website '{domain}' is blocking automated requests. Try manually visiting their careers page instead.")
        elif e.response.status_code == 404:
            raise CompanyScraperError(f"Page not found (404). Please check if '{homepage_url}' is the correct URL.")
        elif e.response.status_code >= 500:
            raise CompanyScraperError(f"Server error ({e.response.status_code}). The website may be temporarily down.")
        else:
            raise CompanyScraperError(f"HTTP error {e.response.status_code}: {e}")
    except requests.RequestException as e:
        raise CompanyScraperError(f"Failed to connect to '{domain}': {str(e)}")
    
    # Parse HTML
    try:
        soup = BeautifulSoup(response.content, "html.parser")
    except Exception as e:
        raise CompanyScraperError(f"Failed to parse HTML: {e}")
    
    # Extract company name
    company_name = _extract_company_name(soup, domain)
    
    # Extract career/jobs URL
    career_url = _extract_career_url(soup, homepage_url)
    
    return {
        "name": company_name,
        "domain": domain,
        "career_url": career_url or "",
    }


def _extract_company_name(soup: BeautifulSoup, domain: str) -> str:
    """
    Extract company name from page content.
    
    Priority:
    1. <meta property="og:site_name">
    2. <title> tag (cleaned)
    3. First <h1> tag
    4. Domain name (capitalized)
    """
    # Try og:site_name meta tag
    og_site_name = soup.find("meta", property="og:site_name")
    if og_site_name and og_site_name.get("content"):
        name = og_site_name["content"].strip()
        if name and len(name) < 100:  # Sanity check
            name = _clean_company_name(name)
            # Handle acronyms: if all lowercase and short, convert to uppercase
            if name.islower() and len(name) <= 4 and name.isalpha():
                return name.upper()
            return name
    
    # Try title tag
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text().strip()
        # Remove common suffixes
        title = re.sub(r"\s*[|-]\s*(Home|Homepage|Official Site|Welcome).*$", "", title, flags=re.IGNORECASE)
        title = _clean_company_name(title)
        if title and len(title) < 100:
            # Handle acronyms
            if title.islower() and len(title) <= 4 and title.isalpha():
                return title.upper()
            return title
    
    # Try first h1 tag
    h1_tag = soup.find("h1")
    if h1_tag:
        h1_text = h1_tag.get_text().strip()
        h1_text = _clean_company_name(h1_text)
        if h1_text and len(h1_text) < 100:
            # Handle acronyms
            if h1_text.islower() and len(h1_text) <= 4 and h1_text.isalpha():
                return h1_text.upper()
            return h1_text
    
    # Fallback: capitalize domain name
    domain_name = domain.split(".")[0]
    # Keep acronyms uppercase (e.g., "aig" -> "AIG", not "Aig")
    if len(domain_name) <= 4 and domain_name.isalpha():
        return domain_name.upper()
    return domain_name.capitalize()


def _clean_company_name(name: str) -> str:
    """Clean company name by removing common suffixes and extra whitespace."""
    # Remove common web suffixes
    name = re.sub(r"\s*[|-]\s*Official.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*[|-]\s*Home.*$", "", name, flags=re.IGNORECASE)
    
    # Handle pipe separators (e.g., "PMAT Inc. | Enhancing Decision Dominance")
    if '|' in name:
        parts = name.split('|')
        # Keep first part (company name) if it's reasonable length
        if parts and len(parts[0].strip()) < 50:
            name = parts[0].strip()
    
    # Remove long descriptive taglines (em dash often separates company from tagline)
    if ' – ' in name:
        parts = name.split(' – ')
        # Keep first part if it's reasonable length (likely the company name)
        if parts and len(parts[0]) < 50:
            name = parts[0]
    # Clean whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _extract_career_url(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """
    Extract career/jobs page URL from links.
    
    Looks for links containing keywords like:
    - careers, jobs, opportunities, join, work-with-us, etc.
    
    Returns the first matching URL, preferring exact keyword matches.
    """
    # Keywords specifically for career/jobs pages (removed "employment" to avoid insurance pages)
    career_keywords = [
        "career",
        "careers",
        "job",
        "jobs",
        "opportunities",
        "join",
        "join-us",
        "work-with-us",
        "working-at",
        "hiring",
        "open-positions",
        "openings",
    ]
    
    # Exclusion patterns to avoid matching insurance/legal/product pages
    exclusion_patterns = [
        'employment-practices',
        'employment-law',
        'employment-liability',
        'employee-benefits',
        'liability',
        'insurance',
        'solutions',
        'product',
        'shop',
        'store',
        'facebook',
        'twitter',
        'linkedin',
        'instagram',
        'youtube',
        'game-pass',
        'xbox',
    ]
    
    # Priority 1: Look for links with exact matches in href
    all_links = soup.find_all("a", href=True)
    
    for link in all_links:
        href = link["href"].lower()
        
        # Skip excluded patterns
        if any(skip in href for skip in exclusion_patterns):
            continue
        
        # Check if href contains career keywords
        for keyword in career_keywords:
            if f"/{keyword}" in href or f"-{keyword}" in href or f"{keyword}/" in href:
                # Convert relative URL to absolute
                full_url = urljoin(base_url, link["href"])
                # Validate it's a proper URL
                if full_url.startswith(("http://", "https://")):
                    return full_url
    
    # Priority 2: Look for links with keywords in text
    for link in soup.find_all("a", href=True):
        href = link["href"].lower()
        text = link.get_text().lower().strip()
        
        # Skip excluded patterns
        if any(skip in href for skip in exclusion_patterns):
            continue
        
        # Check if link text contains career keywords
        for keyword in career_keywords:
            if keyword in text:
                full_url = urljoin(base_url, link["href"])
                if full_url.startswith(("http://", "https://")):
                    return full_url
    
    return None
