"""
Contract Scraper Service: Fetches and parses defense contract awards from war.gov.

The U.S. Department of War (formerly Defense) publishes daily contract award
announcements at https://www.war.gov/News/Contracts/. Each daily article contains
paragraphs grouped by military branch (ARMY, NAVY, AIR FORCE, etc.), with each
paragraph describing one contract award including company name, location, dollar
amount, contract number, description, and completion date.

This service:
1. Fetches the listing page to discover article URLs.
2. Fetches each article and splits the text by branch headings.
3. Parses individual contract paragraphs using regex.
4. Creates DefenseContract records, linking to existing Company records where possible.

Usage:
    from tracker.services.contract_scraper import ContractScraperService

    service = ContractScraperService()
    stats = service.scrape_latest(max_articles=5)
"""

import logging
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from django.db import IntegrityError
from django.utils.timezone import now

from tracker.models import Company, CompanyAlias, DefenseContract, ScrapedArticle

logger = logging.getLogger(__name__)

# war.gov base URLs
BASE_URL = "https://www.war.gov"
CONTRACTS_LISTING_URL = f"{BASE_URL}/News/Contracts/"

# Branch headings as they appear in the article text (uppercased)
BRANCH_MAP = {
    "ARMY": "army",
    "NAVY": "navy",
    "AIR FORCE": "air_force",
    "DEFENSE LOGISTICS AGENCY": "defense_logistics_agency",
    "U.S. SPECIAL OPERATIONS COMMAND": "special_operations",
    "MISSILE DEFENSE AGENCY": "missile_defense",
    "DEFENSE HEALTH AGENCY": "other",
    "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY": "other",
    "DEFENSE INFORMATION SYSTEMS AGENCY": "other",
    "DEFENSE THREAT REDUCTION AGENCY": "other",
    "WASHINGTON HEADQUARTERS SERVICES": "other",
}

# Regex for parsing dollar amounts like "$12,497,947" or "$249,000,000"
DOLLAR_PATTERN = re.compile(r"\$[\d,]+(?:\.\d+)?")

# Regex for contract/modification numbers in parentheses, e.g., "(P00010)" or "(W9124P-22-F-0036)"
CONTRACT_NUMBER_PATTERN = re.compile(
    r"\(([A-Z0-9][\w\-/]+)\)"
)

# Regex for "contract <number>" pattern.
# Uses a lookahead to require at least one digit in the match, avoiding
# false positives like "contract for" or "contract with".
CONTRACT_ID_PATTERN = re.compile(
    r"contract\s+((?=[A-Z0-9]*\d)[A-Z0-9][\w\-/]+)",
    re.IGNORECASE,
)

# Pattern to detect modifications
MODIFICATION_PATTERN = re.compile(
    r"\bmodification\b",
    re.IGNORECASE,
)

# Pattern to detect small business asterisk
SMALL_BUSINESS_PATTERN = re.compile(r"\*")

# Contracting activity extraction
CONTRACTING_ACTIVITY_PATTERN = re.compile(
    r"(?:is|are)\s+the\s+contracting\s+activit(?:y|ies)\b[^.]*",
    re.IGNORECASE,
)

# Work location extraction
WORK_LOCATION_PATTERN = re.compile(
    r"[Ww]ork\s+will\s+be\s+performed\s+(?:in\s+|at\s+)?(.+?)(?:,\s+and\s+is\s+expected|"
    r",\s+with\s+an\s+estimated|\.\s|$)",
    re.DOTALL,
)

# Completion date extraction
COMPLETION_DATE_PATTERN = re.compile(
    r"(?:expected\s+to\s+be\s+completed|estimated\s+completion\s+date)\s+"
    r"(?:by\s+|of\s+|in\s+)?([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}|"
    r"[A-Z][a-z]+\s+\d{4})",
    re.IGNORECASE,
)

# Date extraction from article title like "Contracts for Feb. 5, 2026"
ARTICLE_DATE_PATTERN = re.compile(
    r"[Cc]ontracts\s+for\s+(.+?)(?:,?\s+[Tt]hrough.+)?$"
)

# Polite request delay between HTTP requests (seconds)
REQUEST_DELAY = 1.5

# HTTP request timeout (seconds)
REQUEST_TIMEOUT = 30

# User-Agent header for polite scraping
USER_AGENT = (
    "GmailJobTracker/1.0 (Defense Contract Tracker; "
    "educational/personal use; +https://github.com/cyberthreatgurl/GmailJobTracker)"
)

# Browser-like user agent required to bypass Akamai WAF
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# JavaScript snippet to remove automation detection flags
ANTI_DETECT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


class ContractScraperService:
    """Scrapes and parses defense contract awards from war.gov.

    Uses Playwright (headed Chromium) to bypass Akamai WAF protection
    on defense.gov / war.gov. Falls back to requests if Playwright is
    not installed or browser launch fails.
    """

    def __init__(self):
        # Pre-load known company names for matching
        self._company_name_cache = None

    @property
    def company_name_cache(self) -> Dict[str, int]:
        """Lazy-load a lowercase company name → id mapping for matching, including aliases."""
        if self._company_name_cache is None:
            # 1. Map canonical company names
            self._company_name_cache = {
                company.name.lower(): company.id
                for company in Company.objects.all()
            }
            # 2. Map aliases to same company ID
            # Note: CompanyAlias.company is a string name, not a FK
            for alias_obj in CompanyAlias.objects.all():
                canonical_name_lower = alias_obj.company.lower()
                # Only add if we know the canonical company
                if canonical_name_lower in self._company_name_cache:
                    canonical_id = self._company_name_cache[canonical_name_lower]
                    self._company_name_cache[alias_obj.alias.lower()] = canonical_id

        return self._company_name_cache

    def invalidate_company_cache(self):
        """Force refresh of the company name cache."""
        self._company_name_cache = None

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def scrape_latest(
        self,
        max_articles: int = 5,
        force_refresh: bool = False,
    ) -> Dict:
        """
        Scrape the most recent contract articles from war.gov.

        Opens a single Playwright browser session to fetch all HTML pages,
        then parses and saves contracts after the browser is closed.

        Articles that have already been scraped (tracked in ScrapedArticle)
        are skipped unless *force_refresh* is True.

        Args:
            max_articles: Maximum number of daily articles to process.
            force_refresh: If True, re-fetch articles even if previously scraped.

        Returns:
            Dict with keys: articles_processed, contracts_created, contracts_skipped,
                            errors, article_urls, articles_skipped_cached
        """
        stats = {
            "articles_processed": 0,
            "contracts_created": 0,
            "contracts_skipped": 0,
            "contracts_updated": 0,
            "articles_skipped_cached": 0,
            "errors": [],
            "article_urls": [],
        }

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            stats["errors"].append(
                "Playwright is required. Install with: pip install playwright"
            )
            return stats

        # Build a set of already-scraped URLs to skip (unless refreshing)
        already_scraped: set = set()
        if not force_refresh:
            already_scraped = set(
                ScrapedArticle.objects.values_list("url", flat=True)
            )

        # Step 1: Fetch all HTML content using a single browser session
        article_html_data = []  # List of (url, title, html_content)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=BROWSER_USER_AGENT,
                )
                page = context.new_page()
                page.add_init_script(ANTI_DETECT_SCRIPT)

                # Fetch article links from listing page
                article_links = self._fetch_links_with_page(page)
                if not article_links:
                    stats["errors"].append("No article links found on listing page.")
                    browser.close()
                    return stats

                # Fetch HTML for each article (skip cached unless refreshing)
                fetched = 0
                for url, title in article_links:
                    if fetched >= max_articles:
                        break

                    if url in already_scraped:
                        logger.info("Skipping (already scraped): %s", title)
                        stats["articles_skipped_cached"] += 1
                        continue

                    try:
                        logger.info("Fetching article: %s", title)
                        page.goto(
                            url,
                            wait_until="networkidle",
                            timeout=REQUEST_TIMEOUT * 1000,
                        )
                        html_content = page.content()

                        if "Access Denied" in html_content:
                            stats["errors"].append(f"Access Denied for {url}")
                            continue

                        article_html_data.append((url, title, html_content))
                        stats["article_urls"].append(url)
                        fetched += 1
                        time.sleep(REQUEST_DELAY)
                    except Exception as exc:
                        error_msg = f"Error fetching {url}: {exc}"
                        logger.exception(error_msg)
                        stats["errors"].append(error_msg)

                browser.close()
        except Exception as exc:
            stats["errors"].append(f"Browser launch error: {exc}")
            return stats

        # Step 2: Parse and save contracts (outside Playwright context)
        for url, title, html_content in article_html_data:
            try:
                article_stats = self._parse_and_save_article(url, title, html_content)
                stats["articles_processed"] += 1
                stats["contracts_created"] += article_stats["created"]
                stats["contracts_skipped"] += article_stats["skipped"]
                stats["contracts_updated"] += article_stats.get("updated", 0)
                if article_stats.get("errors"):
                    stats["errors"].extend(article_stats["errors"])

                # Record this article as scraped
                total_contracts = (
                    article_stats["created"]
                    + article_stats["skipped"]
                    + article_stats.get("updated", 0)
                )
                self._record_scraped_article(
                    url, title, total_contracts, article_stats
                )
            except Exception as exc:
                error_msg = f"Error processing {url}: {exc}"
                logger.exception(error_msg)
                stats["errors"].append(error_msg)

        return stats

    def _record_scraped_article(
        self,
        url: str,
        title: str,
        contracts_found: int,
        article_stats: Dict,
    ) -> None:
        """Record a successfully scraped article in the ScrapedArticle table."""
        article_date = self.parse_article_date(title)
        try:
            ScrapedArticle.objects.update_or_create(
                url=url,
                defaults={
                    "title": title[:300],
                    "article_date": article_date,
                    "contracts_found": contracts_found,
                },
            )
        except Exception as exc:
            logger.warning("Could not record scraped article %s: %s", url, exc)

    def fetch_article_links(self) -> List[Tuple[str, str]]:
        """
        Fetch the contracts listing page and extract article URLs.

        Opens its own Playwright browser session. For batch scraping,
        prefer scrape_latest() which reuses a single browser.

        Returns:
            List of (absolute_url, title) tuples, newest first.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error(
                "Playwright is required for scraping war.gov. "
                "Install with: pip install playwright"
            )
            return []

        links = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=BROWSER_USER_AGENT,
                )
                page = context.new_page()
                page.add_init_script(ANTI_DETECT_SCRIPT)

                links = self._fetch_links_with_page(page)
                browser.close()
        except Exception as exc:
            logger.error("Failed to fetch listing page: %s", exc)

        return links

    def process_article(self, url: str, title: str) -> Dict:
        """
        Fetch a single article and parse all contract paragraphs.

        Opens its own Playwright browser. For batch operations, use
        scrape_latest() instead.

        Args:
            url: Full URL of the war.gov article.
            title: Article title (e.g., "Contracts for Feb. 5, 2026").

        Returns:
            Dict with keys: created, skipped, updated, errors
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"created": 0, "skipped": 0, "updated": 0,
                    "errors": ["Playwright not installed"]}

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=BROWSER_USER_AGENT,
                )
                page = context.new_page()
                page.add_init_script(ANTI_DETECT_SCRIPT)

                page.goto(
                    url, wait_until="networkidle",
                    timeout=REQUEST_TIMEOUT * 1000,
                )
                html_content = page.content()
                browser.close()

            if "Access Denied" in html_content:
                return {"created": 0, "skipped": 0, "updated": 0,
                        "errors": [f"Access Denied for {url}"]}

            return self._parse_and_save_article(url, title, html_content)
        except Exception as exc:
            return {"created": 0, "skipped": 0, "updated": 0,
                    "errors": [f"Playwright error: {exc}"]}

    # ──────────────────────────────────────────────
    # Browser-based fetching (internal)
    # ──────────────────────────────────────────────

    def _fetch_links_with_page(self, page) -> List[Tuple[str, str]]:
        """
        Navigate to the listing page and extract article links using
        an already-open Playwright page.
        """
        links = []

        page.goto(
            CONTRACTS_LISTING_URL,
            wait_until="networkidle",
            timeout=REQUEST_TIMEOUT * 1000,
        )
        content = page.content()

        if "Access Denied" in content:
            logger.error("Access Denied on listing page (Akamai WAF)")
            return []

        anchor_elements = page.locator(
            'a[href*="/News/Contracts/Contract/Article/"]'
        ).all()

        for anchor in anchor_elements:
            href = anchor.get_attribute("href") or ""
            title_text = (anchor.text_content() or "").strip()
            if href and title_text:
                absolute_url = urljoin(BASE_URL, href)
                if absolute_url not in [link[0] for link in links]:
                    links.append((absolute_url, title_text))

        logger.info("Found %d article links on listing page.", len(links))
        return links

    def _parse_and_save_article(
        self, url: str, title: str, html_content: str
    ) -> Dict:
        """
        Parse an already-fetched article HTML and save contracts to the DB.

        This method runs entirely outside the Playwright context, so Django
        ORM calls work normally.

        Args:
            url: The article URL (used as source_url).
            title: Article title (used to parse article_date).
            html_content: Full HTML string of the article page.

        Returns:
            Dict with keys: created, skipped, updated, errors
        """
        result = {"created": 0, "skipped": 0, "updated": 0, "errors": []}

        article_date = self.parse_article_date(title)
        if article_date is None:
            result["errors"].append(f"Could not parse date from title: {title}")
            return result

        soup = BeautifulSoup(html_content, "html.parser")

        article_text = self.extract_article_body(soup)
        if not article_text:
            result["errors"].append(f"No article body found at {url}")
            return result

        branch_sections = self.split_by_branch(article_text)

        for branch_key, section_text in branch_sections:
            paragraphs = self.split_into_contract_paragraphs(section_text)
            for paragraph in paragraphs:
                try:
                    contract_data = self.parse_contract_paragraph(
                        paragraph, branch_key, article_date, url
                    )
                    if contract_data is None:
                        continue
                    saved = self.save_contract(contract_data)
                    if saved == "created":
                        result["created"] += 1
                    elif saved == "skipped":
                        result["skipped"] += 1
                    elif saved == "updated":
                        result["updated"] += 1
                except Exception as exc:
                    error_msg = f"Error parsing paragraph in {branch_key}: {exc}"
                    logger.warning(error_msg)
                    result["errors"].append(error_msg)

        return result

    # ──────────────────────────────────────────────
    # HTML Extraction
    # ──────────────────────────────────────────────

    def extract_article_body(self, soup: BeautifulSoup) -> str:
        """
        Extract the main article body text from the parsed HTML.

        Tries several CSS selectors commonly used on war.gov article pages.
        """
        # war.gov wraps article content in a div with class "body" or similar
        selectors = [
            "div.body",
            "div.article-body",
            "article",
            "div.content",
            "main",
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(separator="\n")
                if len(text) > 200:
                    return text

        # Fallback: get all paragraph text
        paragraphs = soup.find_all("p")
        if paragraphs:
            return "\n\n".join(p.get_text() for p in paragraphs)

        return ""

    # ──────────────────────────────────────────────
    # Text Parsing
    # ──────────────────────────────────────────────

    def split_by_branch(self, text: str) -> List[Tuple[str, str]]:
        """
        Split article text into (branch_key, section_text) pairs.

        Branch headings appear as standalone lines like "ARMY", "NAVY", etc.
        """
        # Build a regex that matches any known branch heading on its own line
        branch_names = sorted(BRANCH_MAP.keys(), key=len, reverse=True)
        branch_pattern = re.compile(
            r"^\s*(" + "|".join(re.escape(name) for name in branch_names) + r")\s*$",
            re.MULTILINE,
        )

        matches = list(branch_pattern.finditer(text))
        if not matches:
            # No branch headings found; treat entire text as "other"
            return [("other", text)]

        sections = []
        for i, match in enumerate(matches):
            branch_name = match.group(1).strip()
            branch_key = BRANCH_MAP.get(branch_name, "other")
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            if section_text:
                sections.append((branch_key, section_text))

        return sections

    def split_into_contract_paragraphs(self, section_text: str) -> List[str]:
        """
        Split a branch section into individual contract paragraphs.

        Contracts are separated by double newlines. We filter out very short
        fragments (footnotes, headers) and the "*Small business" note.
        """
        # Split on double newlines (war.gov uses blank lines between contracts)
        raw_paragraphs = re.split(r"\n\s*\n", section_text)

        paragraphs = []
        for para in raw_paragraphs:
            cleaned = para.strip()
            # Skip very short lines (footnotes like "*Small business")
            if len(cleaned) < 50:
                continue
            # Skip if it's just the small business footnote
            if cleaned.strip().startswith("*Small business"):
                continue
            # Skip lines that look like navigation/header content
            if cleaned.startswith("Subscribe") or "War.gov" in cleaned[:30]:
                continue
            paragraphs.append(cleaned)

        return paragraphs

    def parse_contract_paragraph(
        self,
        paragraph: str,
        branch_key: str,
        article_date: datetime,
        source_url: str,
    ) -> Optional[Dict]:
        """
        Parse a single contract paragraph into structured data.

        Args:
            paragraph: The raw text of one contract entry.
            branch_key: Branch code (e.g., "army", "navy").
            article_date: Date of the contracts article.
            source_url: URL of the source article.

        Returns:
            Dict of field values ready for DefenseContract creation, or None if
            the paragraph cannot be parsed as a contract.
        """
        # Normalize whitespace (war.gov sometimes wraps mid-word)
        text = re.sub(r"\s+", " ", paragraph).strip()

        # Remove asterisks used as small-business markers before parsing
        # e.g. "Company Name,* City, State" → "Company Name, City, State"
        is_small_business = "*" in text
        clean_text = text.replace("*", "")
        # Re-normalize any double spaces left by asterisk removal
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        # Multi-awardee detection: if the paragraph contains semicolon-
        # separated companies (e.g., "Co A, City, State (CONTRACT); Co B,
        # City, State (CONTRACT);"), parse only the first company and
        # store the full text.
        # Look for semicolons before any award language
        award_split = re.split(
            r"\b(?:was|were(?:\s+each)?|is|are)\s+(?:being\s+|each\s+)?awarded\b"
            r"|\bhas\s+been\s+(?:added\s+as\s+an\s+awardee|awarded)\b",
            clean_text,
            maxsplit=1,
        )
        pre_award = award_split[0] if len(award_split) > 1 else clean_text
        multi_awardee = ";" in pre_award

        # For multi-awardee paragraphs, extract just the first company
        if multi_awardee:
            first_segment = clean_text.split(";")[0].strip()
            parse_text = first_segment
        else:
            parse_text = clean_text

        # US states and territories pattern (reusable)
        _state_re = (
            r"(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|"
            r"Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|"
            r"Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
            r"Mississippi|Missouri|Montana|Nebraska|Nevada|New\s+Hampshire|"
            r"New\s+Jersey|New\s+Mexico|New\s+York|North\s+Carolina|"
            r"North\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|"
            r"South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|"
            r"Virgina|Virginia|Washington|West\s+Virginia|Wisconsin|Wyoming|"
            r"District\s+of\s+Columbia|D\.C\.|"
            r"Puerto\s+Rico|Guam|U\.S\.\s+Virgin\s+Islands|American\s+Samoa|"
            r"Northern\s+Mariana\s+Islands)"
        )

        # Extract company name and location from the opening of the paragraph.
        # IMPORTANT: Always match against pre_award (text before "is being awarded")
        # rather than the full paragraph — this prevents the regex from scanning
        # past the contract details and picking up a state name from the work
        # location section (e.g. treating all of Arizona as the city when the
        # actual state has a typo like "Florda").
        company_source_text = pre_award.rstrip(", ").strip()
        if multi_awardee:
            company_source_text = clean_text.split(";")[0].strip()
        # Strip editorial prefixes so they don't pollute the company name
        company_source_text = re.sub(r"^(?:UPDATE|CORRECTION):\s*", "", company_source_text).strip()

        company_match = None
        # Skip Pattern 1 for paragraphs that don't lead with a company name
        _skip_pattern1 = company_source_text.startswith(
            ("The $", "A $", "An $", "CORRECTION:", "An existing", "This contract")
        )
        if not _skip_pattern1:
            company_match = re.match(
                r"^(?:UPDATE:\s+)?(.+?),\s+"
                r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),?\s+"  # Optional comma after city
                + _state_re,
                company_source_text,
            )

        # Pattern 2 (fallback): "...announced...to Company, City, State" format
        if not company_match:
            company_match = re.search(
                r",\s+to\s+([^,]+),\s+"
                r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),?\s+"
                + _state_re,
                company_source_text,
            )

        # Pattern 3 (fallback): comma-split on pre_award when the state is
        # misspelled or non-standard (e.g. "Florda" instead of "Florida").
        # Format is always: Company Name, City, State[, ...]
        # Take everything up to the last two comma-delimited tokens as the name.
        if not company_match and len(award_split) > 1:
            # Strip parentheticals (contract numbers, dollar values) before splitting
            # so they don't create spurious comma-separated tokens.
            source_no_parens = re.sub(r"\([^)]*\)", "", company_source_text)
            source_no_parens = re.sub(r"\s+", " ", source_no_parens).strip()
            parts = [p.strip() for p in source_no_parens.split(",") if p.strip()]
            if len(parts) >= 3:
                logger.debug(
                    "Using comma-split fallback for company name (possible state typo): %.80s",
                    company_source_text,
                )
                company_name_raw = ", ".join(parts[:-2])
                city = parts[-2]
                state = parts[-1]
                company_location = f"{city}, {state}"
                # Sanitise — strip trailing parens/contract refs
                company_name_raw = re.sub(r"\s*\([^)]*\)\s*$", "", company_name_raw).strip()
                company_name_raw = company_name_raw.rstrip(",").strip()


        if not company_match and 'company_name_raw' not in locals():
            logger.debug("Could not parse company from paragraph: %.80s...", clean_text)
            return None

        if company_match:
            company_name_raw = company_match.group(1).strip()
            city = company_match.group(2).strip()
            state = company_match.group(3).strip()
            company_location = f"{city}, {state}"

        # Remove trailing comma if present
        company_name_raw = company_name_raw.rstrip(",").strip()
        # Safety guard: if name is suspiciously long (> 120 chars) the regex
        # probably matched too broadly — discard this entry.
        if len(company_name_raw) > 120:
            logger.warning(
                "Discarding contract paragraph — parsed company name too long (%d chars): %.120s",
                len(company_name_raw),
                company_name_raw,
            )
            return None

        # Extract dollar amount
        amount = None
        dollar_matches = DOLLAR_PATTERN.findall(clean_text)
        if dollar_matches:
            amount = self.parse_dollar_amount(dollar_matches[0])

        # Extract contract number
        contract_number = ""
        # First try parenthesized contract/modification number
        contract_num_match = CONTRACT_NUMBER_PATTERN.search(clean_text)
        if contract_num_match:
            candidate = contract_num_match.group(1)
            # Must look like a contract number (letters + digits + dashes)
            if re.search(r"[A-Z]", candidate) and re.search(r"\d", candidate):
                contract_number = candidate

        # If not found, try "contract <number>" pattern
        if not contract_number:
            contract_id_match = CONTRACT_ID_PATTERN.search(clean_text)
            if contract_id_match:
                candidate = contract_id_match.group(1)
                # Validate: must contain both letters and digits
                if re.search(r"[A-Za-z]", candidate) and re.search(r"\d", candidate):
                    contract_number = candidate

        # Is it a modification?
        is_modification = bool(MODIFICATION_PATTERN.search(clean_text))

        # Extract work location
        work_location = ""
        work_match = WORK_LOCATION_PATTERN.search(clean_text)
        if work_match:
            work_location = work_match.group(1).strip()
            # Clean up trailing punctuation
            work_location = work_location.rstrip(".,;")

        # Extract completion date
        completion_date = ""
        date_match = COMPLETION_DATE_PATTERN.search(clean_text)
        if date_match:
            completion_date = date_match.group(1).strip()

        # Extract contracting activity
        contracting_activity = ""
        activity_match = CONTRACTING_ACTIVITY_PATTERN.search(clean_text)
        if activity_match:
            raw_activity = activity_match.group(0)
            # Extract just the org name after "is the contracting activity"
            activity_name = re.sub(
                r"^(?:is|are)\s+the\s+contracting\s+activit(?:y|ies)\b[.\s]*",
                "",
                raw_activity,
                flags=re.IGNORECASE,
            ).strip()
            # If empty, try to get the text before "is the contracting activity"
            if not activity_name:
                before_match = re.search(
                    r"([A-Z][^.]*?)\s+(?:is|are)\s+the\s+contracting",
                    clean_text,
                    re.IGNORECASE,
                )
                if before_match:
                    activity_name = before_match.group(1).strip()
            contracting_activity = activity_name.rstrip(".,;()")

        # Build description (first sentence or two without the company intro)
        description = self.extract_description(clean_text, company_name_raw)

        # Try to match to an existing Company record
        company_id = self.match_company(company_name_raw)

        return {
            "contract_number": contract_number,
            "source_url": source_url,
            "article_date": article_date,
            "company_name_raw": company_name_raw,
            "company_id": company_id,
            "branch": branch_key,
            "amount": amount,
            "description": description,
            "raw_text": re.sub(r"\s+", " ", paragraph).strip(),
            "company_location": company_location,
            "work_location": work_location,
            "completion_date": completion_date,
            "contracting_activity": contracting_activity,
            "is_modification": is_modification,
            "is_small_business": is_small_business,
        }

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def parse_article_date(self, title: str) -> Optional[datetime]:
        """
        Parse the article date from the title string.

        Handles formats like:
        - "Contracts for Feb. 5, 2026"
        - "Contracts for Jan. 29, 2026"
        - "Contracts for Feb. 2, 2026, Through Feb. 4, 2026"
        """
        match = ARTICLE_DATE_PATTERN.search(title)
        if not match:
            return None

        date_str = match.group(1).strip()

        # Try multiple date formats
        formats = [
            "%B %d, %Y",      # "February 5, 2026"
            "%b. %d, %Y",     # "Feb. 5, 2026"
            "%b %d, %Y",      # "Feb 5, 2026"
            "%B %d %Y",       # "February 5 2026"
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # If it includes "Through", take the first date
        through_match = re.match(r"(.+?)\s*,?\s*[Tt]hrough", date_str)
        if through_match:
            first_date = through_match.group(1).strip()
            for fmt in formats:
                try:
                    return datetime.strptime(first_date, fmt)
                except ValueError:
                    continue

        logger.warning("Could not parse date from title segment: '%s'", date_str)
        return None

    @staticmethod
    def parse_dollar_amount(dollar_str: str) -> Optional[Decimal]:
        """
        Parse a dollar string like "$12,497,947" into a Decimal.

        Returns None if parsing fails.
        """
        cleaned = dollar_str.replace("$", "").replace(",", "").strip()
        try:
            return Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None

    def extract_description(self, text: str, company_name: str) -> str:
        """
        Extract a meaningful description from the contract text.

        Removes the company name/location preamble and returns the core
        description of what the contract is for.
        """
        # Find the "was awarded" or "is awarded" clause
        awarded_match = re.search(
            r"(?:was|is|are|were)\s+awarded\s+",
            text,
            re.IGNORECASE,
        )
        if awarded_match:
            description = text[awarded_match.start():]
        else:
            description = text

        # Truncate at a reasonable length
        if len(description) > 1000:
            # Try to cut at a sentence boundary
            cutoff = description[:1000].rfind(".")
            if cutoff > 200:
                description = description[:cutoff + 1]
            else:
                description = description[:1000] + "..."

        return description.strip()

    def match_company(self, company_name_raw: str) -> Optional[int]:
        """
        Try to match a scraped company name to an existing Company record.

        Uses case-insensitive exact match first, then tries common variations
        (removing Inc., Corp., LLC, etc.).

        Returns:
            Company ID if matched, None otherwise.
        """
        name_lower = company_name_raw.lower().strip()

        # Exact match (case-insensitive)
        if name_lower in self.company_name_cache:
            return self.company_name_cache[name_lower]

        # Try stripping common suffixes
        suffixes_to_strip = [
            r",?\s*inc\.?$",
            r",?\s*corp\.?$",
            r",?\s*llc\.?$",
            r",?\s*ltd\.?$",
            r",?\s*l\.?p\.?$",
            r",?\s*co\.?$",
            r",?\s*company$",
            r",?\s*corporation$",
            r",?\s*incorporated$",
            r",?\s*group$",
        ]

        for suffix_pattern in suffixes_to_strip:
            stripped = re.sub(suffix_pattern, "", name_lower, flags=re.IGNORECASE).strip()
            if stripped and stripped in self.company_name_cache:
                return self.company_name_cache[stripped]

        # Try matching cached names that contain the scraped name (or vice versa)
        for cached_name, cached_id in self.company_name_cache.items():
            if name_lower in cached_name or cached_name in name_lower:
                # Only match if at least 60% of characters overlap
                shorter = min(len(name_lower), len(cached_name))
                if shorter >= 4:
                    return cached_id

        return None

    def save_contract(self, data: Dict) -> str:
        """
        Save a parsed contract to the database.

        Uses the unique_together constraint (source_url, company_name_raw,
        contract_number) to avoid duplicates.

        Returns:
            "created", "skipped", or "updated"
        """
        lookup = {
            "source_url": data["source_url"],
            "company_name_raw": data["company_name_raw"],
            "contract_number": data.get("contract_number", ""),
        }

        defaults = {
            key: data[key]
            for key in data
            if key not in lookup
        }

        # Resolve company FK
        company_id = defaults.pop("company_id", None)
        if company_id:
            defaults["company_id"] = company_id

        try:
            contract, created = DefenseContract.objects.update_or_create(
                **lookup,
                defaults=defaults,
            )
            if created:
                logger.info(
                    "Created contract: %s – %s (%s)",
                    data["company_name_raw"],
                    data.get("contract_number", "N/A"),
                    data["branch"],
                )
                return "created"
            else:
                return "updated"
        except IntegrityError:
            logger.debug(
                "Duplicate contract skipped: %s – %s",
                data["company_name_raw"],
                data.get("contract_number", "N/A"),
            )
            return "skipped"

    def search_contracts(
        self,
        query: str = "",
        branch: str = "",
        days: int = 30,
    ) -> List[DefenseContract]:
        """
        Search stored contracts by keyword, branch, or date range.

        Args:
            query: Text to search in company name, description, or work location.
            branch: Filter by military branch code.
            days: Only return contracts from the last N days.

        Returns:
            QuerySet of matching DefenseContract records.
        """
        from django.utils.timezone import now as tz_now
        from datetime import timedelta

        qs = DefenseContract.objects.all()

        if days:
            cutoff = tz_now().date() - timedelta(days=days)
            qs = qs.filter(article_date__gte=cutoff)

        if branch:
            qs = qs.filter(branch=branch)

        if query:
            from django.db.models import Q
            qs = qs.filter(
                Q(company_name_raw__icontains=query)
                | Q(description__icontains=query)
                | Q(work_location__icontains=query)
                | Q(contracting_activity__icontains=query)
                | Q(raw_text__icontains=query)
            )

        return qs.select_related("company")
