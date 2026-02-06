"""
Management command to fetch defense contract awards from war.gov.

Usage:
    # Fetch latest 5 articles (default)
    python manage.py fetch_contracts

    # Fetch up to 10 articles
    python manage.py fetch_contracts --max-articles 10

    # Dry run - show what would be fetched without saving
    python manage.py fetch_contracts --dry-run

    # Search existing contracts
    python manage.py fetch_contracts --search "cybersecurity"
"""

from django.core.management.base import BaseCommand

from tracker.services.contract_scraper import ContractScraperService


class Command(BaseCommand):
    help = "Fetch defense contract awards from war.gov and store in database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-articles",
            type=int,
            default=5,
            help="Maximum number of daily contract articles to process (default: 5)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show article links that would be fetched without saving contracts",
        )
        parser.add_argument(
            "--force-refresh",
            action="store_true",
            help="Re-fetch articles even if already scraped (bypass cache)",
        )
        parser.add_argument(
            "--search",
            type=str,
            default="",
            help="Search existing stored contracts by keyword (does not fetch new data)",
        )

    def handle(self, *args, **options):
        service = ContractScraperService()

        # Search mode: query existing contracts
        if options["search"]:
            self._search_contracts(service, options["search"])
            return

        # Dry run: just show article links
        if options["dry_run"]:
            self._dry_run(service, options["max_articles"])
            return

        # Normal mode: fetch and save
        self._fetch_contracts(
            service, options["max_articles"], options["force_refresh"]
        )

    def _fetch_contracts(self, service, max_articles, force_refresh=False):
        """Fetch and save contract awards."""
        mode = "REFRESH ALL" if force_refresh else "incremental"
        self.stdout.write(
            self.style.NOTICE(
                f"🏛️  Fetching up to {max_articles} contract articles "
                f"from war.gov ({mode})..."
            )
        )

        stats = service.scrape_latest(
            max_articles=max_articles, force_refresh=force_refresh
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("═" * 50))
        self.stdout.write(self.style.SUCCESS("📊 Scraping Results"))
        self.stdout.write(self.style.SUCCESS("═" * 50))
        self.stdout.write(f"  📰 Articles processed: {stats['articles_processed']}")
        cached = stats.get('articles_skipped_cached', 0)
        if cached:
            self.stdout.write(f"  📦 Articles skipped (already scraped): {cached}")
        self.stdout.write(
            self.style.SUCCESS(f"  ✨ Contracts created:  {stats['contracts_created']}")
        )
        self.stdout.write(f"  🔄 Contracts updated:  {stats.get('contracts_updated', 0)}")
        self.stdout.write(f"  ⏭️  Contracts skipped:  {stats['contracts_skipped']}")

        if stats["errors"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("⚠️  Warnings/Errors:"))
            for error in stats["errors"]:
                self.stdout.write(f"    • {error}")

        if stats["article_urls"]:
            self.stdout.write("")
            self.stdout.write("📰 Articles processed:")
            for url in stats["article_urls"]:
                self.stdout.write(f"    • {url}")

        self.stdout.write("")

    def _dry_run(self, service, max_articles):
        """Show article links without fetching content."""
        self.stdout.write(
            self.style.NOTICE("🔍 Dry run — fetching article links only...")
        )

        links = service.fetch_article_links()
        if not links:
            self.stdout.write(self.style.WARNING("No article links found."))
            return

        self.stdout.write(f"\nFound {len(links)} article(s) on listing page:")
        for i, (url, title) in enumerate(links[:max_articles], 1):
            self.stdout.write(f"  {i}. {title}")
            self.stdout.write(f"     {url}")

        remaining = len(links) - max_articles
        if remaining > 0:
            self.stdout.write(f"\n  ... and {remaining} more (increase --max-articles)")

        self.stdout.write("")

    def _search_contracts(self, service, query):
        """Search existing contracts by keyword."""
        self.stdout.write(
            self.style.NOTICE(f'🔍 Searching stored contracts for "{query}"...')
        )

        contracts = service.search_contracts(query=query, days=0)
        count = contracts.count()

        if count == 0:
            self.stdout.write(self.style.WARNING("No matching contracts found."))
            return

        self.stdout.write(f"\n📋 Found {count} matching contract(s):\n")

        for contract in contracts[:25]:
            amount = contract.amount_display
            self.stdout.write(f"  🏢 {contract.company_name_raw}")
            self.stdout.write(f"     💰 {amount} | 🎖️ {contract.get_branch_display()}")
            self.stdout.write(f"     📅 {contract.article_date} | 📍 {contract.company_location}")
            if contract.contract_number:
                self.stdout.write(f"     📝 {contract.contract_number}")
            self.stdout.write("")

        if count > 25:
            self.stdout.write(f"  ... and {count - 25} more results.")
