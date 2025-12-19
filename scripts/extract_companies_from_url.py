import argparse
import json
import os
import sys
from urllib.parse import urlparse

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES_JSON = os.path.join(REPO_ROOT, "json", "companies.json")
CAREER_PAGES_JSON = os.path.join(REPO_ROOT, "json", "company_career_pages.json")


def get_domain(netloc):
    netloc = netloc.strip().lower()
    if not netloc:
        return None
    if "@" in netloc:
        netloc = netloc.split("@", 1)[-1]
    if ":" in netloc:
        netloc = netloc.split(":", 1)[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    parts = netloc.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def guess_company(domain):
    core = domain.split(".")[0]
    return core.capitalize()


def process_url(url, page_domain_only=False):
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return {}, set()

    page_domain = get_domain(urlparse(url).netloc)
    if page_domain_only and page_domain:
        return {page_domain: guess_company(page_domain)}, {guess_company(page_domain)}
    return {}, set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--from-file", action="store_true")
    ap.add_argument("--page-domain-only", action="store_true")
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args()

    if args.from_file:
        with open(CAREER_PAGES_JSON) as f:
            data = json.load(f)
        urls = [(e["company"], e["url"]) for e in data.get("career_pages", [])]
    else:
        urls = [(None, args.url)]

    all_map, all_known = {}, set()
    for name, url in urls:
        if name:
            print(f"[{name}] {url}")
        m, k = process_url(url, args.page_domain_only)
        all_map.update(m)
        all_known.update(k)

    print(
        json.dumps({"domain_to_company": all_map, "known": sorted(all_known)}, indent=2)
    )

    if args.update and all_map:
        with open(COMPANIES_JSON) as f:
            companies = json.load(f)
        companies.setdefault("domain_to_company", {}).update(all_map)
        companies.setdefault("known", []).extend(
            [k for k in all_known if k not in companies["known"]]
        )
        with open(COMPANIES_JSON, "w") as f:
            json.dump(companies, f, indent=2)
        print("Updated companies.json")


if __name__ == "__main__":
    main()
