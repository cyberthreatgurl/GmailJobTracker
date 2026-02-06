"""
Views for Defense Contract Awards.

Provides a searchable, filterable listing of defense contract awards
scraped from war.gov, plus an AJAX endpoint to trigger scraping.
"""

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render
from django.http import JsonResponse
from django.utils.timezone import now

from tracker.models import DefenseContract, ScrapedArticle
from tracker.services.contract_scraper import ContractScraperService

logger = logging.getLogger(__name__)

# Export view functions so they are importable from tracker.views
__all__ = [
    "defense_contracts",
    "fetch_contracts_ajax",
]


@login_required
def defense_contracts(request):
    """
    Display searchable listing of defense contract awards.

    Supports filtering by:
    - search query (company name, description, work location)
    - military branch
    - date range (days back)
    """
    # Read filter parameters from GET
    search_query = request.GET.get("q", "").strip()
    branch_filter = request.GET.get("branch", "")
    days_back = request.GET.get("days", "30")

    try:
        days_back = int(days_back)
    except (ValueError, TypeError):
        days_back = 30

    # Build queryset with filters
    contracts_qs = DefenseContract.objects.select_related("company")

    if days_back > 0:
        cutoff_date = now().date() - timedelta(days=days_back)
        contracts_qs = contracts_qs.filter(article_date__gte=cutoff_date)

    if branch_filter:
        contracts_qs = contracts_qs.filter(branch=branch_filter)

    if search_query:
        contracts_qs = contracts_qs.filter(
            Q(company_name_raw__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(work_location__icontains=search_query)
            | Q(contracting_activity__icontains=search_query)
            | Q(raw_text__icontains=search_query)
        )

    contracts_qs = contracts_qs.order_by("-article_date", "branch", "company_name_raw")

    # Summary statistics
    total_value = contracts_qs.aggregate(total=Sum("amount"))["total"] or 0
    total_count = contracts_qs.count()

    # Branch choices for the filter dropdown
    branch_choices = DefenseContract.BRANCH_CHOICES

    # Date range options
    date_range_options = [
        (7, "Last 7 days"),
        (14, "Last 14 days"),
        (30, "Last 30 days"),
        (60, "Last 60 days"),
        (90, "Last 90 days"),
        (0, "All time"),
    ]

    # Format total value for display
    if total_value >= 1_000_000_000:
        total_value_display = f"${total_value / 1_000_000_000:,.2f}B"
    elif total_value >= 1_000_000:
        total_value_display = f"${total_value / 1_000_000:,.1f}M"
    else:
        total_value_display = f"${total_value:,.0f}"

    # Scraped article cache info
    scraped_articles_count = ScrapedArticle.objects.count()
    last_scraped = ScrapedArticle.objects.order_by("-scraped_at").first()

    context = {
        "contracts": contracts_qs,
        "search_query": search_query,
        "branch_filter": branch_filter,
        "days_back": days_back,
        "total_count": total_count,
        "total_value_display": total_value_display,
        "branch_choices": branch_choices,
        "date_range_options": date_range_options,
        "scraped_articles_count": scraped_articles_count,
        "last_scraped": last_scraped,
    }
    return render(request, "tracker/defense_contracts.html", context)


@login_required
def fetch_contracts_ajax(request):
    """
    AJAX endpoint to trigger scraping of latest contract articles.

    POST parameters:
    - max_articles: Number of articles to scrape (default: 5, max: 20)

    Returns JSON with scraping statistics.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    max_articles = request.POST.get("max_articles", "5")
    try:
        max_articles = min(int(max_articles), 20)
    except (ValueError, TypeError):
        max_articles = 5

    force_refresh = request.POST.get("force_refresh", "") == "1"

    try:
        service = ContractScraperService()
        stats = service.scrape_latest(
            max_articles=max_articles, force_refresh=force_refresh
        )
        return JsonResponse({
            "success": True,
            "articles_processed": stats["articles_processed"],
            "contracts_created": stats["contracts_created"],
            "contracts_skipped": stats["contracts_skipped"],
            "contracts_updated": stats.get("contracts_updated", 0),
            "articles_skipped_cached": stats.get("articles_skipped_cached", 0),
            "errors": stats["errors"][:10],  # Limit error messages
        })
    except Exception as exc:
        logger.exception("Error during contract scraping")
        return JsonResponse({
            "success": False,
            "error": str(exc),
        }, status=500)
