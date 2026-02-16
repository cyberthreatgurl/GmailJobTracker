#!/usr/bin/env python
"""Re-scrape articles with corrected regex to fix company name extraction."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from tracker.models import DefenseContract, ScrapedArticle
from tracker.services.contract_scraper import ContractScraperService
import django.db.models as m

# Find contracts with long company names (indicates parsing issue)
contracts = DefenseContract.objects.filter(
    data_source='war_gov'
).annotate(
    name_len=m.functions.Length('company_name_raw')
).filter(
    name_len__gt=100
)

# Get unique URLs
urls = sorted(set(c.source_url for c in contracts))

print(f"Found {contracts.count()} contracts with long names from {len(urls)} articles")
print(f"Will delete {contracts.count()} contracts and re-scrape {len(urls)} articles")
print()

# Delete the problematic contracts
print("Deleting problematic contracts...")
deleted_count = contracts.delete()[0]
print(f"Deleted {deleted_count} contracts")
print()

# Delete the ScrapedArticle cache so they can be re-fetched
print("Clearing ScrapedArticle cache for these URLs...")
for url in urls:
    ScrapedArticle.objects.filter(url=url).delete()
print(f"Cleared {len(urls)} cached articles")
print()

# Re-scrape each article
scraper = ContractScraperService()
for i, url in enumerate(urls, 1):
    print(f"[{i}/{len(urls)}] Re-scraping {url}")
    result = scraper.fetch_and_parse_article(url)
    print(f"  Created: {result['created']}, Updated: {result['updated']}, Skipped: {result['skipped']}")
    if result['errors']:
        print(f"  Errors: {result['errors']}")
    print()

print("Done! Checking results...")
# Check if we still have any long company names
remaining = DefenseContract.objects.filter(
    data_source='war_gov'
).annotate(
    name_len=m.functions.Length('company_name_raw')
).filter(
    name_len__gt=100
)

if remaining.exists():
    print(f"⚠️ Still have {remaining.count()} contracts with long names:")
    for c in remaining[:5]:
        print(f"  - {c.company_name_raw[:80]}...")
else:
    print("✓ All contracts now have properly extracted company names!")
