import logging
import re
import csv
import io
import time
from urllib.parse import quote_plus
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date, parse_datetime
from django.db.models import Q
from tracker.models import SamGovOpportunity
from tracker.services.sam_gov_service import SamGovClient

logger = logging.getLogger(__name__)


def _build_opportunity_ui_link(solicitation_number='', notice_id='', api_ui_link=''):
    """Build a stable SAM.gov URL for an opportunity.

    Direct /opp/.../view links returned by the API can 404 for many notice types,
    including award notices. SAM.gov's live UI uses a structured search query with
    sfm[simpleSearch][keywordTags], and that URL lands on the relevant result rather
    than the empty default search shell.
    """
    query_value = (solicitation_number or notice_id or '').strip()
    if query_value:
        encoded_value = quote_plus(query_value.lower())
        return (
            "https://sam.gov/search/?index=opp&page=1&pageSize=25"
            "&sort=-modifiedDate"
            "&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"
            f"&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bkey%5D={encoded_value}"
            f"&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D={encoded_value}"
            "&sfm%5Bstatus%5D%5Bis_active%5D=true"
            "&sfm%5Bstatus%5D%5Bis_inactive%5D=true"
        )
    return api_ui_link or "https://sam.gov/content/opportunities"

@login_required
def get_opportunity_debug(_request, opportunity_id):
    """Fetch raw API response for debugging."""
    opp = get_object_or_404(SamGovOpportunity.objects.only('raw_response'), id=opportunity_id)
    return JsonResponse(opp.raw_response or {}, safe=False)

@login_required
def opportunities_dashboard(request):
    """
    Search and browse SAM.gov contract opportunities.
    Fetches real-time data from SAM.gov API and saves interesting ones locally.
    """
    query = request.GET.get("q", "")
    page_number = request.GET.get("page", 1)

    # Handle CSV Upload
    if request.method == "POST" and request.FILES.get("csv_file"):
        try:
            csv_file = request.FILES["csv_file"]
            # Use utf-8-sig to handle potential BOM from Excel exports
            decoded_file = csv_file.read().decode("utf-8-sig")
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)

            count = 0
            new_count = 0

            for row in reader:
                mapped_data = _map_csv_row_to_api_format(row)
                if not mapped_data:
                    continue

                saved, created = _save_opportunity(mapped_data, save_mode='create_or_update')
                if saved:
                    count += 1
                if created:
                    new_count += 1

            if count > 0:
                messages.success(request, f"Successfully ingested {count} opportunities from CSV ({new_count} new).")
            else:
                messages.warning(request, "No valid opportunities found in CSV.")

        except Exception as e:
            logger.error(f"Error processing CSV upload: {e}")
            messages.error(request, f"Error processing CSV: {e}")

        return redirect(request.path)

    # If user clicks "Fetch Latest"
    if "fetch" in request.GET:
        client = SamGovClient()

        # Determine start date: Max of (90 days ago, Last Ingested Date)
        # This optimizes for speed (incremental update) while staying within API limits
        default_start_date = (datetime.now() - timedelta(days=90)).date()
        start_date = default_start_date

        latest_opp = SamGovOpportunity.objects.order_by("-posted_date").first()
        if latest_opp and latest_opp.posted_date:
            # If we have recent data, start from the last known posted date
            # This avoids re-fetching months of data we already have
            if latest_opp.posted_date > default_start_date:
                start_date = latest_opp.posted_date

        params = {
            "limit": 10,
            "sort": "-postedDate",
            "postedFrom": start_date.strftime("%m/%d/%Y"),
            "postedTo": datetime.now().strftime("%m/%d/%Y")
        }

        if query:
            # If query is present during fetch, search API by title/keyword
            params["title"] = query

        try:
            api_response = client.search_opportunities(params=params)

            if "opportunitiesData" in api_response:
                count = 0
                new_count = 0
                for item in api_response["opportunitiesData"]:
                    # save_mode='create_only' ensures we don't overwrite existing records
                    saved, created = _save_opportunity(item, save_mode='create_only')
                    if saved:
                        count += 1
                    if created:
                        new_count += 1

                if new_count > 0:
                    messages.success(request, f"Fetched {count} opportunities ({new_count} new).")
                elif count > 0:
                    messages.info(request, f"Fetched {count} opportunities (all already existed).")
                else:
                    messages.info(request, "No opportunities found in API response.")

            elif "error" in api_response:
                messages.error(request, f"API Error: {api_response['error']}")
            else:
                messages.info(request, "No opportunities found.")

        except Exception as e:
            logger.error(f"Error fetching opportunities: {e}")
            messages.error(request, f"Error interacting with SAM.gov: {e}")

        # Redirect api clean URL after fetch prevents re-submission
        url = request.path
        params_list = []
        if query:
            params_list.append(f"q={query}")

        if params_list:
            url += "?" + "&".join(params_list)

        return redirect(url)

    # Display saved opportunities (Local Search)
    qs = SamGovOpportunity.objects.defer("raw_response").order_by("-posted_date", "-fetched_at")

    # Apply active contract ignore rules (same rules as defense contracts page)
    from tracker.models import ContractIgnoreRule
    from django.db.models import Q as _Q
    ignored_naics = set()
    ignored_psc = set()
    ignored_terms = []
    for rule in ContractIgnoreRule.objects.filter(is_active=True).prefetch_related('naics_codes'):
        if rule.rule_type == 'naics':
            ignored_naics.add(rule.value)
        elif rule.rule_type == 'psc':
            ignored_psc.add(rule.value)
        elif rule.rule_type in ('domain', 'sector'):
            ignored_naics.update(rule.naics_codes.values_list('code', flat=True))
        elif rule.rule_type == 'term':
            ignored_terms.append(rule.value)
    if ignored_naics:
        qs = qs.exclude(naics_code__in=ignored_naics)
    if ignored_psc:
        qs = qs.exclude(product_service_code__in=ignored_psc)
    for term in ignored_terms:
        qs = qs.exclude(
            _Q(title__icontains=term) | _Q(description__icontains=term)
        )

    # Local filtering if query persists (searching local DB)
    if query:
        search_terms = query.split()
        for term in search_terms:
            qs = qs.filter(
                Q(title__icontains=term) |
                Q(description__icontains=term) |
                Q(department__icontains=term) |
                Q(office__icontains=term) |
                Q(solicitation_number__icontains=term) |
                Q(naics_code__icontains=term) |
                Q(product_service_code__icontains=term)
            )

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(page_number)

    for opp in page_obj.object_list:
        opp.display_ui_link = _build_opportunity_ui_link(
            solicitation_number=opp.solicitation_number or '',
            api_ui_link=opp.ui_link or '',
        )

    return render(request, "tracker/opportunities.html", {
        "page_obj": page_obj,
        "query": query,
    })



def _parse_api_date(date_str):
    if not date_str:
        return None
    d = parse_date(date_str)
    if d:
        return d
    dt = parse_datetime(date_str)
    if dt:
        return dt.date()
    return None

def _normalize_naics_code(raw_value):
    """
    Normalize a raw naics_code value to a 6-digit numeric code string.
    SAM.gov sometimes returns the full description instead of the numeric code.
    Handles formats: '541519', '541519 - IT Services', 'Information Technology'.
    Returns the best available value (numeric code preferred, original if no match).
    """
    import re
    if not raw_value:
        return raw_value
    stripped = str(raw_value).strip()
    # If it starts with 4-8 digits, those digits are the code
    m = re.match(r'^(\d{4,8})', stripped)
    if m:
        return m.group(1)
    # Otherwise try a description lookup against the NAICSCode table
    from tracker.models import NAICSCode
    match = NAICSCode.objects.filter(description__iexact=stripped).first()
    if match:
        return match.code
    # Partial description match (some descriptions differ slightly in punctuation)
    match = NAICSCode.objects.filter(description__icontains=stripped[:40]).first()
    if match:
        return match.code
    return stripped


def _save_opportunity(data, save_mode='create_or_update'):
    """
    Helpers to save/update a SamGovOpportunity from API dict.
    save_mode: 'create_only' - don't overwrite existing
               'create_or_update' - standard behavior

    Returns (record, created_bool)
    """
    try:
        solicitation = data.get("solicitationNumber")
        if not solicitation:
            solicitation = data.get("noticeId")

        if not solicitation:
            return None, False

        # If in create_only mode, check existence first
        if save_mode == 'create_only':
            if SamGovOpportunity.objects.filter(solicitation_number=solicitation).exists():
                return None, False

        notice_id = data.get("noticeId")
        ui_link = _build_opportunity_ui_link(
            solicitation_number=solicitation,
            notice_id=notice_id or '',
            api_ui_link=data.get("uiLink", ""),
        )

        opp, created = SamGovOpportunity.objects.update_or_create(
            solicitation_number=solicitation,
            defaults={
                "title": data.get("title", ""),
                "posted_date": _parse_api_date(data.get("postedDate")),
                "response_date": _parse_api_date(data.get("responseDeadLine")),
                "type": data.get("type", ""),
                "base_type": data.get("baseType", ""),
                "award": data.get("award", {}),
                "full_parent_path_name": data.get("fullParentPathName", ""),
                "department": data.get("department", ""),
                "office": data.get("office", ""),
                "sub_office": data.get("subOffice", ""),
                "naics_code": _normalize_naics_code(data.get("naicsCode", "") or data.get("naics", "")),
                "product_service_code": data.get("classificationCode") or data.get("pscCode") or data.get("psc") or "",
                "naics_codes": data.get("naicsCodes", []),
                "point_of_contact": data.get("pointOfContact", []),
                "description": data.get("description", ""),
                "resource_links": data.get("resourceLinks", []),
                "ui_link": ui_link,
                "raw_response": data,  # Save full JSON for debugging
            }
        )
        return opp, created
    except Exception as e:
        logger.error(f"Failed to save opportunity {data.get('noticeId')}: {e}")
        return None, False


def _map_csv_row_to_api_format(row):
    """
    Map CSV export row to API-compatible format for ingestion.
    Assumes standard SAM.gov export columns.
    """
    # Key fields
    solicitation = row.get("Notice ID") or row.get("NoticeID") or row.get("solicitationNumber")
    title = row.get("Opportunity Title") or row.get("Title")

    if not solicitation or not title:
        return {} # Empty creates nothing

    # Dates
    posted_date = _parse_csv_date(row.get("Last Published Date") or row.get("Posted Date"))
    response_date = _parse_csv_date(row.get("Current Response Date") or row.get("Response Deadline"))

    # POC
    poc = []
    if row.get("POC Name"):
        poc = [{"fullName": row.get("POC Name"), "email": row.get("POC Email")}]

    # Construct dict mimicking API structure for compatibility with _save_opportunity
    return {
        "solicitationNumber": solicitation,
        "noticeId": solicitation,
        "title": title,
        "type": row.get("Contract Opportunity Type") or row.get("Type"),
        "postedDate": posted_date,
        "responseDeadLine": response_date,
        "description": row.get("Description"),
        "department": row.get("Sub Tier Name") or row.get("Department/Ind. Agency"),
        "office": row.get("Contracting Office"),
        "subOffice": row.get("Sub Tier"),
        "naicsCode": row.get("NAICS Code") or row.get("NAICS"),
        "classificationCode": row.get("Classification Code") or row.get("PSC"),
        "pointOfContact": poc,
        "uiLink": f"https://sam.gov/search/?index=opp&page=1&sort=-relevance&pageSize=25&sf=SF&kwd={solicitation}&mode=search",
        "raw_response": row # special handling -> we put row into raw_response so `_save_ops` picks it up
    }

def _parse_csv_date(date_str):
    """
    Parse SAM.gov CSV date format (e.g. 'Oct 21, 2024 02:44 pm UTC')
    Returns YYYY-MM-DD string or None
    """
    if not date_str or not isinstance(date_str, str) or date_str.lower() == 'nan':
        return None

    try:
        # Try cleaning UTC suffix first
        clean = date_str.replace(" UTC", "").replace(" pm", " PM").replace(" am", " AM").strip()

        # Format: "Feb 23, 2026 09:00 PM"
        try:
            dt = datetime.strptime(clean, "%b %d, %Y %I:%M %p")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

        return clean
    except Exception:
        logger.warning(f"Could not parse CSV date: {date_str}")
        return None


@login_required
def refresh_opportunity_json(_request, opportunity_id):
    """
    AJAX endpoint: refresh a single opportunity and return updated fields as JSON.
    Used by the inline 'Load Description' button on the opportunities page.
    """
    try:
        opp = SamGovOpportunity.objects.get(pk=opportunity_id)
        client = SamGovClient()

        # Step 1: If the stored description is already a SAM.gov URL, resolve it directly.
        # This is the common case: the API returned a URL instead of text at ingest time.
        stored_desc = opp.description or ''
        if 'api.sam.gov/prod/opportunities' in stored_desc:
            desc = _resolve_description(client, stored_desc, '')
            if desc:
                opp.description = desc
                opp.save(update_fields=['description'])
                return JsonResponse({'ok': True, 'description': desc})

        # Step 2: Try the search API to get a fresh copy of the record.
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=364)
        found_data = _fetch_with_date_window(client, opp.solicitation_number, start_date, end_date)
        if not found_data and opp.posted_date and opp.posted_date < start_date:
            old_start = opp.posted_date
            old_end = old_start + timedelta(days=364)
            found_data = _fetch_with_date_window(client, opp.solicitation_number, old_start, old_end)
        if found_data:
            result, _ = _save_opportunity(found_data, save_mode='create_or_update')
            if result:
                desc = _resolve_description(client, result.description or '', found_data.get('noticeId', ''))
                if desc:
                    result.description = desc
                    result.save(update_fields=['description'])
                    return JsonResponse({'ok': True, 'description': desc})

        # Step 3: Last-resort direct description fetch using the internal noticeId UUID.
        # The solicitation_number (e.g. "1333HK26C00000007") doesn't work here — we need
        # the UUID that SAM.gov uses internally, sourced from raw_response or ui_link.
        notice_id = ''
        if opp.raw_response and isinstance(opp.raw_response, dict):
            notice_id = opp.raw_response.get('noticeId', '')
        if not notice_id and opp.ui_link:
            m = re.search(r'/opp/([0-9a-f]{8,}[0-9a-f]*)/view', opp.ui_link, re.IGNORECASE)
            if m:
                notice_id = m.group(1)
        if notice_id:
            direct_desc = client.fetch_description(notice_id)
            if direct_desc:
                opp.description = direct_desc
                opp.save(update_fields=['description'])
                return JsonResponse({'ok': True, 'description': direct_desc})
        return JsonResponse({'ok': False, 'error': 'Not found in SAM.gov API'})
    except SamGovOpportunity.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Record not found'}, status=404)
    except Exception as e:
        logger.error(f'refresh_opportunity_json error for {opportunity_id}: {e}')
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def refresh_opportunity(request, opportunity_id):
    """
    Manually refresh a single opportunity from SAM.gov API.
    Attempts to find the record within the last year first.
    If not found and the local record is older, tries searching the older time window.
    """
    try:
        opp = SamGovOpportunity.objects.get(pk=opportunity_id)
        client = SamGovClient()

        # Strategy 1: Search recent (last 364 days)
        # This catches any active updates or recently posted items
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=364)

        found_data = _fetch_with_date_window(client, opp.solicitation_number, start_date, end_date)

        # Strategy 2: If nothing found, try the specific posted_date window from DB
        # Only needed if the local record is older than our search window
        if not found_data and opp.posted_date and opp.posted_date < start_date:
            # Shift window to capture the specific old posted date
            old_start = opp.posted_date
            old_end = old_start + timedelta(days=364)
            found_data = _fetch_with_date_window(client, opp.solicitation_number, old_start, old_end)

        # Strategy 3: Iterate back 3 years if still missing (useful when posted_date is unknown)
        if not found_data and not opp.posted_date:
            for i in range(1, 4):  # Try 3 previous years
                s = start_date - timedelta(days=365 * i)
                e = s + timedelta(days=365)
                # Respect API limits (wait slightly between calls)
                time.sleep(1)
                found_data = _fetch_with_date_window(client, opp.solicitation_number, s, e)
                if found_data:
                    break

        if found_data:
            # Force update
            result, _ = _save_opportunity(found_data, save_mode='create_or_update')
            if result:
                # Resolve description URL if the API returned a link instead of text
                desc = _resolve_description(client, result.description or '', opp.solicitation_number)
                if desc:
                    result.description = desc
                    result.save(update_fields=['description'])
                messages.success(request, f"Successfully refreshed '{opp.solicitation_number}'")
            else:
                messages.error(request, "Failed to update record (save error).")
        else:
            # Fallback: try fetching description directly by notice ID
            direct_desc = client.fetch_description(opp.solicitation_number)
            if direct_desc:
                opp.description = direct_desc
                opp.save(update_fields=['description'])
                messages.success(request, f"Description loaded from SAM.gov for '{opp.solicitation_number}'")
            else:
                messages.warning(request, "Opportunity not found in API even after checking past 3 years.")

    except SamGovOpportunity.DoesNotExist:
        messages.error(request, "Opportunity not found.")
    except Exception as e:
        logger.error(f"Error refreshing opp {opportunity_id}: {e}")
        messages.error(request, f"Refresh failed: {e}")

    return redirect("opportunities_dashboard")

def _resolve_description(client, desc, notice_id):
    """
    If `desc` is a SAM.gov description URL, follow it to fetch the real content.
    Falls back to a direct notice-description lookup using `notice_id`.
    Returns the resolved description text (may be HTML) or empty string.
    """
    if desc and 'api.sam.gov/prod/opportunities' in desc:
        # Extract noticeId from the URL if present
        m = re.search(r'noticeid=([^&\s]+)', desc, re.IGNORECASE)
        url_notice_id = m.group(1) if m else notice_id
        fetched = client.fetch_description(url_notice_id)
        if fetched:
            return fetched
    elif desc:
        return desc
    # Try direct lookup using the stored notice_id as a last resort
    if notice_id:
        return client.fetch_description(notice_id) or ''
    return ''


def _fetch_with_date_window(client, solicitation, start_date, end_date):
    """Helper to try fetching with a specific date window."""

    # Try solicitationNumber first
    params = {
        "solicitationNumber": solicitation,
        "limit": 1,
        "postedFrom": start_date.strftime("%m/%d/%Y"),
        "postedTo": end_date.strftime("%m/%d/%Y"),
    }
    data = client.search_opportunities(params)
    if data.get("opportunitiesData"):
        return data["opportunitiesData"][0]

    # If not found, try noticeId (it might be a special notice where solicitationNumber is not set)
    params.pop("solicitationNumber")
    params["noticeId"] = solicitation
    data = client.search_opportunities(params)
    if data.get("opportunitiesData"):
        return data["opportunitiesData"][0]

    # If not found, try keyword search (for cases like "FA251827RCNECTS" vs "FA2518-27-R-CNECTS")
    # This acts as a fuzzy fallback
    params.pop("noticeId")
    params["keywords"] = solicitation
    data = client.search_opportunities(params)
    if data.get("opportunitiesData"):
        return data["opportunitiesData"][0]

    return None
