"""
Views for Defense Contract Awards.

Provides a searchable, filterable listing of defense contract awards
scraped from war.gov, plus an AJAX endpoint to trigger scraping.
"""

import json
import logging
from datetime import timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils.timezone import now

from tracker.forms import CompanyEditForm
from tracker.models import Company, DefenseContract, ScrapedArticle
from tracker.services.contract_scraper import ContractScraperService
from django.core.management import call_command
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
import os

logger = logging.getLogger(__name__)

# Export view functions so they are importable from tracker.views
__all__ = [
    "defense_contracts",
    "fetch_contracts_ajax",
    "create_company_popup",
    "link_contract_company",
    "search_companies_for_linking",
    "upload_contract_json",
    "upload_contracts_csv",
]


@login_required
def defense_contracts(request):
    """
    Display searchable listing of government contract awards.

    Supports filtering by:
    - data source (war_gov, usaspending, all)
    - search query (company name, description, work location)
    - military branch (war.gov only)
    - awarding agency (USASpending only)
    - date range (days back)
    """
    # Read filter parameters from GET
    search_query = request.GET.get("q", "").strip()
    source_filter = request.GET.get("source", "all")
    branch_filter = request.GET.get("branch", "")
    agency_filter = request.GET.get("agency", "").strip()
    days_back = request.GET.get("days", "90")  # Default to 90 days for broader view

    try:
        days_back = int(days_back)
    except (ValueError, TypeError):
        days_back = 30

    # Build queryset with filters
    contracts_qs = DefenseContract.objects.select_related("company")

    # Source filter
    if source_filter and source_filter != "all":
        contracts_qs = contracts_qs.filter(data_source=source_filter)

    if days_back > 0:
        cutoff_date = now().date() - timedelta(days=days_back)
        contracts_qs = contracts_qs.filter(article_date__gte=cutoff_date)

    # Branch filter (war.gov only)
    if branch_filter:
        contracts_qs = contracts_qs.filter(branch=branch_filter)

    # Agency filter (USASpending only)
    if agency_filter:
        contracts_qs = contracts_qs.filter(awarding_agency__icontains=agency_filter)

    if search_query:
        contracts_qs = contracts_qs.filter(
            Q(company_name_raw__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(work_location__icontains=search_query)
            | Q(contracting_activity__icontains=search_query)
            | Q(awarding_agency__icontains=search_query)
            | Q(awarding_sub_agency__icontains=search_query)
            | Q(raw_text__icontains=search_query)
        )

    contracts_qs = contracts_qs.order_by("-article_date", "branch", "company_name_raw")

    # Summary statistics
    total_value = contracts_qs.aggregate(total=Sum("amount"))["total"] or 0
    total_count = contracts_qs.count()

    # Source counts for display
    source_counts = {
        "all": DefenseContract.objects.count(),
        "war_gov": DefenseContract.objects.filter(data_source="war_gov").count(),
        "usaspending": DefenseContract.objects.filter(data_source="usaspending").count(),
    }

    # Data source choices for filter dropdown
    source_choices = [
        ("all", "All Sources"),
        ("war_gov", f"DoD (war.gov) - {source_counts['war_gov']} contracts"),
        ("usaspending", f"Federal (USASpending) - {source_counts['usaspending']} contracts"),
    ]

    # Branch choices for the filter dropdown
    branch_choices = DefenseContract.BRANCH_CHOICES

    # Get unique awarding agencies for dropdown (top 10 by frequency)
    from django.db.models import Count
    top_agencies = (
        DefenseContract.objects.filter(data_source="usaspending")
        .values("awarding_agency")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    agency_choices = [a["awarding_agency"] for a in top_agencies if a["awarding_agency"]]

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
        "source_filter": source_filter,
        "source_choices": source_choices,
        "source_counts": source_counts,
        "branch_filter": branch_filter,
        "branch_choices": branch_choices,
        "agency_filter": agency_filter,
        "agency_choices": agency_choices,
        "days_back": days_back,
        "total_count": total_count,
        "total_value_display": total_value_display,
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


@login_required
def create_company_popup(request):
    """
    Popup window for creating a Company from a defense contract award.

    GET: Display pre-filled form (company name, location from query params).
    POST: Validate and create the company, update companies.json.
    """
    created_company = None

    if request.method == "POST":
        form = CompanyEditForm(request.POST)
        if form.is_valid():
            company_name = (form.cleaned_data.get("name") or "").strip()
            if not company_name:
                messages.error(request, "❌ Please enter a company name.")
            else:
                domain = (form.cleaned_data.get("domain") or "").strip()
                # Create the company
                new_company = form.save(commit=False)
                new_company.confidence = 1.0
                new_company.first_contact = now()
                new_company.last_contact = now()
                if not new_company.status:
                    new_company.status = "new"
                new_company.save()
                created_company = new_company
                messages.success(request, f"✅ Company '{new_company.name}' created!")

                # Sync to companies.json
                _sync_company_to_json(new_company, domain)

                # Link matching DefenseContract records to the new company
                linked = DefenseContract.objects.filter(
                    company__isnull=True,
                    company_name_raw__iexact=company_name,
                ).update(company=new_company)
                if linked:
                    messages.info(
                        request,
                        f"🔗 Linked {linked} existing contract(s) to {new_company.name}.",
                    )
        else:
            error_parts = []
            for field, errors in form.errors.items():
                for error in errors:
                    error_parts.append(f"{field}: {error}")
            messages.error(request, f"❌ {'; '.join(error_parts)}")
    else:
        # GET: Pre-fill from query parameters
        initial = {}
        if request.GET.get("name"):
            initial["name"] = request.GET["name"]
        if request.GET.get("location"):
            initial["location"] = request.GET["location"]
        if request.GET.get("notes"):
            initial["notes"] = request.GET["notes"]
        form = CompanyEditForm(initial=initial)

    return render(request, "tracker/create_company_popup.html", {
        "form": form,
        "created_company": created_company,
    })


@login_required
def link_contract_company(request, contract_id):
    """
    AJAX endpoint to manually link or unlink a DefenseContract to an existing Company record.

    POST params:
    - company_id: PK of the Company to link, or empty/"0" to unlink

    Returns JSON with the linked company details, or {company_id: null} on unlink.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        contract = DefenseContract.objects.get(pk=contract_id)
    except DefenseContract.DoesNotExist:
        return JsonResponse({"error": "Contract not found"}, status=404)

    company_id = request.POST.get("company_id", "").strip()
    if not company_id or company_id == "0":
        contract.company = None
        contract.save(update_fields=["company", "updated_at"])
        logger.info("Unlinked contract %s from company", contract_id)
        return JsonResponse({"success": True, "company_id": None, "company_name": None})

    try:
        company = Company.objects.get(pk=int(company_id))
    except (Company.DoesNotExist, ValueError):
        return JsonResponse({"error": "Company not found"}, status=404)

    contract.company = company
    contract.save(update_fields=["company", "updated_at"])
    
    # Auto-link other contracts with the same raw company name
    updated_qs = DefenseContract.objects.filter(
        company_name_raw=contract.company_name_raw,
        company__isnull=True
    )
    updated_ids = list(updated_qs.values_list('id', flat=True))
    updated_count = updated_qs.update(company=company)

    logger.info("Linked contract %s -> company '%s' (%s). Auto-linked %d others.", 
        contract_id, company.name, company.id, updated_count)
    return JsonResponse({
        "success": True,
        "company_id": company.id,
        "company_name": company.name,
        "company_url": f"/label_companies/?company={company.id}",
        "updated_count": updated_count,
        "updated_ids": updated_ids,
    })


@login_required
def search_companies_for_linking(request):
    """
    AJAX company search used by the contract linking modal.

    GET params:
    - q: Search string (min 1 char)

    Returns JSON list of up to 20 matching Company records.
    """
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"companies": []})

    companies = list(
        Company.objects.filter(name__icontains=q)
        .order_by("name")[:20]
        .values("id", "name", "status", "location")
    )
    return JsonResponse({"companies": companies})


def _sync_company_to_json(company, domain):
    """Add a newly created company to companies.json."""
    try:
        companies_json_path = Path("json/companies.json")
        if not companies_json_path.exists():
            return
        with open(companies_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        changes = False

        # Add to known array
        if "known" not in data:
            data["known"] = []
        if company.name not in data["known"]:
            data["known"].append(company.name)
            changes = True

        # Add domain mapping
        if domain:
            if "domain_to_company" not in data:
                data["domain_to_company"] = {}
            if domain not in data["domain_to_company"]:
                data["domain_to_company"][domain] = company.name
                changes = True

        if changes:
            with open(companies_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Failed to sync company to companies.json: %s", exc)


@login_required
def upload_contract_json(request):
    """
    Handle manual upload of a USASpending contract JSON file.

    This function parses a JSON file containing a single contract record
    (as returned by the USASpending API) and creates or updates a
    DefenseContract record.
    """
    if request.method == "POST" and request.FILES.get("contract_json"):
        try:
            json_file = request.FILES.get("contract_json")
            data = json.load(json_file)
            
            # Simple validation: ensure it's a dict and has 'piid'
            if not isinstance(data, dict):
                raise ValueError("JSON content must be a dictionary")
            
            piid = data.get("piid")
            if not piid:
                raise ValueError("Missing 'piid' (Contract Number) in JSON")

            # Extract fields
            award_data = {
                "award_id": str(data.get("id", "")),
                "generated_internal_id": data.get("generated_unique_award_id", ""),
                "description": data.get("description", ""),
                "amount": float(data.get("total_obligation", 0.0) or 0.0),
                "article_date": data.get("date_signed") or now().date(),
                "data_source": "usaspending",
                "usaspending_published": True,
            }

            # Create or update contract
            contract, created = DefenseContract.objects.update_or_create(
                contract_number=piid,
                defaults=award_data
            )
            
            action = "Created" if created else "Updated"
            messages.success(request, f"{action} contract {piid} from JSON upload.")
            logger.info("Manually uploaded contract %s (%s)", piid, action)

        except Exception as e:
            logger.error("Failed to upload contract JSON: %s", e)
            messages.error(request, f"Error uploading JSON: {str(e)}")
    
    return redirect("defense_contracts")

@login_required
def upload_contracts_csv(request):
    """
    Handle manual upload of a USASpending contracts CSV file.
    """
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file selected.")
        elif not csv_file.name.lower().endswith('.csv'):
            messages.error(request, "Please upload a valid CSV file.")
        else:
            tmp_path = None
            try:
                # Save to temporary file
                path = default_storage.save(f"tmp/{csv_file.name}", ContentFile(csv_file.read()))
                # get full path for management command
                tmp_path = os.path.join(settings.MEDIA_ROOT, path)

                # Call management command
                call_command('load_contracts_csv', tmp_path)
                messages.success(request, f"Successfully imported contracts from {csv_file.name}.")
                
            except Exception as e:
                logger.exception("Error uploading contracts CSV")
                messages.error(request, f"Error processing file: {str(e)}")
            finally:
                # Clean up
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

    return redirect("defense_contracts")

