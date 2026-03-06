"""
Management command to fetch government contract awards from war.gov and USASpending.gov.

Usage:
    # Fetch from war.gov (default, backward compatible)
    python manage.py fetch_contracts

    # Fetch from USASpending.gov
    python manage.py fetch_contracts --source usaspending --limit 500

    # Fetch from both sources
    python manage.py fetch_contracts --source all --limit 50

    # Filter by agencies (USASpending only)
    python manage.py fetch_contracts --source usaspending --agencies 012 097

    # War.gov specific options
    python manage.py fetch_contracts --source war_gov --max-articles 10 --force-refresh

    # Search existing contracts
    python manage.py fetch_contracts --search "cybersecurity"
"""

from django.core.management.base import BaseCommand

from tracker.services.contract_scraper import ContractScraperService
from tracker.services.usaspending_service import USASpendingService


class Command(BaseCommand):
    help = "Fetch government contract awards from war.gov and/or USASpending.gov."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            choices=["war_gov", "usaspending", "all"],
            default="war_gov",
            help="Data source: war_gov (DoD only), usaspending (all agencies), or all (default: war_gov)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Maximum contracts to fetch from USASpending API (default: 100)",
        )
        parser.add_argument(
            "--agencies",
            nargs="+",
            default=None,
            help="Filter by agency codes for USASpending (e.g., --agencies 012 097)",
        )
        # War.gov specific arguments
        parser.add_argument(
            "--max-articles",
            type=int,
            default=20,
            help="Maximum number of daily contract articles to process from war.gov (default: 5)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="[war.gov only] Show article links without saving contracts",
        )
        parser.add_argument(
            "--force-refresh",
            action="store_true",
            help="[war.gov only] Re-fetch articles even if already scraped (bypass cache)",
        )
        # Search argument (works for both sources)
        parser.add_argument(
            "--search",
            type=str,
            default="",
            help="Search existing stored contracts by keyword (does not fetch new data)",
        )

    def handle(self, *args, **options):
        # Search mode: query existing contracts
        if options["search"]:
            self._search_contracts(options["search"])
            return

        source = options["source"]

        # Route to appropriate service(s)
        if source == "war_gov":
            self._fetch_war_gov(options)
        elif source == "usaspending":
            self._fetch_usaspending(options)
        elif source == "all":
            self._fetch_war_gov(options)
            self.stdout.write("")  # Blank line between sources
            self._fetch_usaspending(options)

    def _fetch_war_gov(self, options):
        """Fetch contracts from war.gov (DoD only)."""
        service = ContractScraperService()

        # Dry run: just show article links
        if options["dry_run"]:
            self._dry_run_war_gov(service, options["max_articles"])
            return

        # Normal mode: fetch and save
        mode = "REFRESH ALL" if options["force_refresh"] else "incremental"
        self.stdout.write(
            self.style.NOTICE(
                f"🏛️  Fetching up to {options['max_articles']} DoD contract articles "
                f"from war.gov ({mode})..."
            )
        )

        stats = service.scrape_latest(
            max_articles=options["max_articles"], force_refresh=options["force_refresh"]
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("═" * 50))
        self.stdout.write(self.style.SUCCESS("📊 war.gov Results (DoD Contracts)"))
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

        if stats.get("errors"):
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("⚠️  Warnings/Errors:"))
            for error in stats["errors"]:
                self.stdout.write(f"    • {error}")

        if stats.get("article_urls"):
            self.stdout.write("")
            self.stdout.write("📰 Articles processed:")
            for url in stats["article_urls"]:
                self.stdout.write(f"    • {url}")

        self.stdout.write("")

    def _fetch_usaspending(self, options):
        """Fetch contracts from USASpending.gov (all federal agencies)."""
        service = USASpendingService()
        limit = options["limit"]
        agencies = options.get("agencies")

        agency_msg = f" (agencies: {', '.join(agencies)})" if agencies else ""
        self.stdout.write(
            self.style.NOTICE(
                f"🏛️  Fetching up to {limit} federal contracts from USASpending.gov{agency_msg}..."
            )
        )

        try:
            result = service.fetch_and_save_contracts(
                limit=limit, agency_codes=agencies
            )

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("═" * 50))
            self.stdout.write(self.style.SUCCESS("📊 USASpending.gov Results (All Agencies)"))
            self.stdout.write(self.style.SUCCESS("═" * 50))
            self.stdout.write(
                self.style.SUCCESS(f"  ✨ Contracts created:  {result['created']}")
            )
            self.stdout.write(f"  ⏭️  Contracts skipped:  {result['skipped']}")
            if result.get("errors", 0) > 0:
                self.stdout.write(
                    self.style.WARNING(f"  ⚠️  Errors:            {result['errors']}")
                )
            self.stdout.write("")

        except Exception as exc:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"❌ USASpending API error: {exc}"))
            self.stdout.write("")
            raise

    def _dry_run_war_gov(self, service, max_articles):
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

    def _search_contracts(self, query):
        """Search existing contracts by keyword (both sources)."""
        from tracker.models import DefenseContract
        
        self.stdout.write(
            self.style.NOTICE(f'🔍 Searching stored contracts for "{query}"...')
        )

        contracts = DefenseContract.objects.filter(
            description__icontains=query
        ).order_by("-article_date")
        
        count = contracts.count()

        if count == 0:
            self.stdout.write(self.style.WARNING("No matching contracts found."))
            return

        self.stdout.write(f"\n📋 Found {count} matching contract(s):\n")

        for contract in contracts[:25]:
            amount = contract.amount_display
            source_icon = "🎖️" if contract.data_source == "war_gov" else "🏛️"
            source_label = contract.get_data_source_display() if hasattr(contract, 'get_data_source_display') else contract.data_source.upper()
            
            self.stdout.write(f"  🏢 {contract.company_name_raw}")
            self.stdout.write(f"     💰 {amount} | {source_icon} {source_label}")
            self.stdout.write(f"     📅 {contract.article_date} | 📍 {contract.company_location or contract.work_location or 'N/A'}")
            
            if contract.data_source == "war_gov" and contract.contract_number:
                self.stdout.write(f"     📝 {contract.contract_number}")
            elif contract.data_source == "usaspending":
                if contract.awarding_agency:
                    self.stdout.write(f"     🏢 {contract.awarding_agency}")
            
            self.stdout.write("")

        if count > 25:
            self.stdout.write(f"  ... and {count - 25} more results.")
        
        self.stdout.write("")