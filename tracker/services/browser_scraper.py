"""Shared browser-backed scraping helpers for static and rendered pages."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
        "Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

ANTI_DETECT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""

ATS_HOST_PATTERNS = (
    re.compile(r"(^|\.)talent\.", re.I),
    re.compile(r"(^|\.)icims\.com$", re.I),
    re.compile(r"(^|\.)workdayjobs\.com$", re.I),
    re.compile(r"(^|\.)greenhouse\.io$", re.I),
    re.compile(r"(^|\.)lever\.co$", re.I),
)

LOW_SIGNAL_PHRASES = (
    "enable javascript",
    "javascript is required",
    "please turn on javascript",
    "access denied",
    "checking your browser",
    "cloudflare",
)


def should_use_browser_first(url: str) -> bool:
    """Return True for hosts that are commonly JS-rendered ATS platforms."""
    hostname = (urlparse(url).hostname or "").lower()
    hostname = hostname.removeprefix("www.")
    return any(pattern.search(hostname) for pattern in ATS_HOST_PATTERNS)


def should_fallback_to_browser(
    url: str,
    extracted_text: str,
    status_code: Optional[int] = None,
) -> bool:
    """Decide whether a static scrape result should escalate to browser rendering."""
    if should_use_browser_first(url):
        return True
    if status_code in {401, 403, 429}:
        return True

    normalized_text = re.sub(r"\s+", " ", (extracted_text or "")).strip().lower()
    if len(normalized_text) < 200:
        return True
    return any(phrase in normalized_text for phrase in LOW_SIGNAL_PHRASES)


def extract_visible_text_from_html(html: str) -> str:
    """Extract visible text from HTML for heuristic decisions and fallbacks."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
        element.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def fetch_static_page(url: str, timeout: int = 20000) -> Dict[str, Any]:
    """Fetch HTML with requests and return a normalized page result."""
    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=max(timeout / 1000, 1),
            allow_redirects=True,
        )
    except requests.Timeout:
        return {
            "success": False,
            "source_method": "static",
            "final_url": url,
            "status_code": 408,
            "html": "",
            "text": "",
            "captured_json": [],
            "error": "Request timed out. The page took too long to load.",
        }
    except requests.RequestException as exc:
        return {
            "success": False,
            "source_method": "static",
            "final_url": url,
            "status_code": None,
            "html": "",
            "text": "",
            "captured_json": [],
            "error": f"Failed to fetch page: {exc}",
        }

    html = response.text or ""
    text = extract_visible_text_from_html(html)
    status_code = response.status_code
    error = None
    if status_code >= 400:
        if status_code == 403:
            error = "Access denied (403). The website is blocking automated requests."
        elif status_code == 404:
            error = "Page not found (404). Please check the URL."
        else:
            error = f"HTTP error {status_code}"

    return {
        "success": status_code < 400,
        "source_method": "static",
        "final_url": response.url,
        "status_code": status_code,
        "html": html,
        "text": text,
        "captured_json": [],
        "error": error,
    }


def fetch_rendered_page(
    url: str,
    wait_for: Optional[str] = None,
    timeout: int = 20000,
    capture_json: bool = False,
) -> Dict[str, Any]:
    """Fetch a page with Playwright and return rendered HTML plus visible text."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "success": False,
            "source_method": "rendered",
            "final_url": url,
            "status_code": None,
            "html": "",
            "text": "",
            "captured_json": [],
            "error": "Playwright is not installed. Run: python -m playwright install chromium",
        }

    captured_json_payloads = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 1600},
                user_agent=REQUEST_HEADERS["User-Agent"],
            )
            page = context.new_page()
            page.add_init_script(ANTI_DETECT_SCRIPT)

            if capture_json:
                def handle_response(response):
                    if len(captured_json_payloads) >= 10:
                        return
                    try:
                        if response.request.resource_type not in {"xhr", "fetch"}:
                            return
                        content_type = response.headers.get("content-type", "")
                        if "application/json" not in content_type.lower():
                            return
                        captured_json_payloads.append({
                            "url": response.url,
                            "data": response.json(),
                        })
                    except Exception:
                        logger.debug("Skipping non-JSON browser response from %s", response.url)

                page.on("response", handle_response)

            page.goto(url, wait_until="networkidle", timeout=timeout)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=min(timeout, 5000))

            html = page.content()
            final_url = page.url
            browser.close()
    except Exception as exc:
        return {
            "success": False,
            "source_method": "rendered",
            "final_url": url,
            "status_code": None,
            "html": "",
            "text": "",
            "captured_json": captured_json_payloads,
            "error": f"Rendered page fetch failed: {exc}",
        }

    return {
        "success": True,
        "source_method": "rendered",
        "final_url": final_url,
        "status_code": 200,
        "html": html,
        "text": extract_visible_text_from_html(html),
        "captured_json": captured_json_payloads,
        "error": None,
    }


def fetch_best_effort_page(
    url: str,
    wait_for: Optional[str] = None,
    timeout: int = 20000,
    browser_first: Optional[bool] = None,
    capture_json: bool = False,
) -> Dict[str, Any]:
    """Fetch with static requests first unless heuristics call for rendered fetch first."""
    use_browser_first = should_use_browser_first(url) if browser_first is None else browser_first

    if use_browser_first:
        rendered_result = fetch_rendered_page(
            url,
            wait_for=wait_for,
            timeout=timeout,
            capture_json=capture_json,
        )
        if rendered_result["success"]:
            return rendered_result

        static_result = fetch_static_page(url, timeout=timeout)
        if static_result["success"]:
            return static_result
        return rendered_result if rendered_result.get("error") else static_result

    static_result = fetch_static_page(url, timeout=timeout)
    if static_result["success"] and not should_fallback_to_browser(
        url,
        static_result.get("text", ""),
        static_result.get("status_code"),
    ):
        return static_result

    rendered_result = fetch_rendered_page(
        url,
        wait_for=wait_for,
        timeout=timeout,
        capture_json=capture_json,
    )
    if rendered_result["success"]:
        return rendered_result
    if static_result["success"]:
        return static_result
    return rendered_result if rendered_result.get("error") else static_result


__all__ = [
    "REQUEST_HEADERS",
    "extract_visible_text_from_html",
    "fetch_best_effort_page",
    "fetch_rendered_page",
    "fetch_static_page",
    "should_fallback_to_browser",
    "should_use_browser_first",
]