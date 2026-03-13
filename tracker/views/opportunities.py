import logging
import csv
import io
import time
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date, parse_datetime
from django.conf import settings
from django.db.models import Q
from tracker.models import SamGovOpportunity
from tracker.services.sam_gov_service import SamGovClient

logger = logging.getLogger(__name__)

@login_required
def get_opportunity_debug(request, opportunity_id):
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
    psc_query = request.GET.get("psc", "")
    exclude_psc_query = request.GET.get("exclude_psc", "")
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
        if psc_query:
            params_list.append(f"psc={psc_query}")
        if exclude_psc_query:
            params_list.append(f"exclude_psc={exclude_psc_query}")
            
        if params_list:
            url += "?" + "&".join(params_list)
            
        return redirect(url)

    # Display saved opportunities (Local Search)
    qs = SamGovOpportunity.objects.defer("raw_response").order_by("-posted_date", "-fetched_at")
    
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
                Q(product_service_code__icontains=term)
            )
            
    if psc_query:
        qs = qs.filter(product_service_code__icontains=psc_query)

    if exclude_psc_query:
        qs = qs.exclude(product_service_code__icontains=exclude_psc_query)

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(page_number)

    return render(request, "tracker/opportunities.html", {
        "page_obj": page_obj,
        "query": query,
        "psc_query": psc_query,
        "exclude_psc_query": exclude_psc_query,
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

        # Construct public UI link manually if noticeId is present (more reliable than API's workspace link)
        ui_link = data.get("uiLink", "")
        notice_id = data.get("noticeId")
        if notice_id:
             ui_link = f"https://sam.gov/opp/{notice_id}/view"

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
                "naics_code": data.get("naicsCode", "") or data.get("naics", ""),
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
    except Exception as e:
        logger.warning(f"Could not parse CSV date: {date_str}")
        return None


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
                 messages.success(request, f"Successfully refreshed '{opp.solicitation_number}'")
            else:
                 messages.error(request, "Failed to update record (save error).")
        else:
            # If we tried all strategies and failed
            messages.warning(request, "Opportunity not found in API even after checking past 3 years.")

    except SamGovOpportunity.DoesNotExist:
        messages.error(request, "Opportunity not found.")
    except Exception as e:
        logger.error(f"Error refreshing opp {opportunity_id}: {e}")
        messages.error(request, f"Refresh failed: {e}")
        
    return redirect("opportunities_dashboard")

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
