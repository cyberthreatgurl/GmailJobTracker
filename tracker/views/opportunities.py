import logging
import csv
import io
from datetime import datetime
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date, parse_datetime
from tracker.models import SamGovOpportunity
from tracker.services.sam_gov_service import SamGovClient

logger = logging.getLogger(__name__)

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
        # Set search range starting Jan 1, 2024 to catch opportunities with future deadlines
        params = {
            "limit": 10, 
            "sort": "-postedDate",
            "postedFrom": "01/01/2024",
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
        return redirect(f"{request.path}?q={query}" if query else request.path)

    # Display saved opportunities (Local Search)
    qs = SamGovOpportunity.objects.all().order_by("-posted_date", "-fetched_at")
    
    # Local filtering if query persists (searching local DB)
    if query:
        qs = qs.filter(title__icontains=query)

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(page_number)

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
                "naics_code": data.get("naicsCode", ""),
                "naics_codes": data.get("naicsCodes", []),
                "point_of_contact": data.get("pointOfContact", []),
                "description": data.get("description", ""),
                "resource_links": data.get("resourceLinks", []),
                "ui_link": data.get("uiLink", ""),
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
        "uiLink": f"https://sam.gov/opp/{solicitation}/view",
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
    """
    try:
        opp = SamGovOpportunity.objects.get(pk=opportunity_id)
        client = SamGovClient()
        
        # Try finding it exactly by solicitation number
        params = {"solicitationNumber": opp.solicitation_number, "limit": 1}
        response = client.search_opportunities(params=params)
        
        # Check success
        if "opportunitiesData" in response and response["opportunitiesData"]:
            item = response["opportunitiesData"][0]
            # Force update 
            result, _ = _save_opportunity(item, save_mode='create_or_update')
            if result:
                 messages.success(request, f"Successfully refreshed '{opp.solicitation_number}'")
            else:
                 messages.error(request, "Failed to update record.")
        elif "error" in response:
             messages.error(request, f"API Error: {response['error']}")
        else:
             messages.warning(request, "Opportunity not found in API (might be archived or removed).")

    except SamGovOpportunity.DoesNotExist:
        messages.error(request, "Opportunity not found.")
    except Exception as e:
        logger.error(f"Error refreshing opp {opportunity_id}: {e}")
        messages.error(request, f"Refresh failed: {e}")
        
    return redirect("opportunities_dashboard")
