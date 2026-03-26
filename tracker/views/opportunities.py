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
from django.db.models import F, Q, OrderBy
from django.db.models.functions import Lower
from tracker.models import Company, NAICSCode, PSCCode, SamGovOpportunity
from tracker.services.sam_gov_service import SamGovClient

logger = logging.getLogger(__name__)


OPPORTUNITY_SORT_DEFAULTS = {
    "title": "asc",
    "posted": "desc",
    "response": "desc",
    "type": "asc",
    "department": "asc",
    "naics": "asc",
    "psc": "asc",
}


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


def _query_items(querydict, exclude=None):
    """Return query params as a flat list of key/value pairs for hidden inputs."""
    excluded = set(exclude or [])
    items = []
    for key in querydict.keys():
        if key in excluded:
            continue
        for value in querydict.getlist(key):
            if value not in (None, ''):
                items.append((key, value))
    return items


def _update_querystring(querydict, updates=None, exclude=None):
    """Return a new encoded query string with specified values updated or removed."""
    params = querydict.copy()
    for key in exclude or []:
        params.pop(key, None)

    for key, value in (updates or {}).items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params.setlist(key, [str(value)])

    return params.urlencode()


def _normalize_lookup_filter(raw_value, normalizer):
    """Normalize an autocomplete filter value to its canonical code when possible."""
    stripped = (str(raw_value).strip() if raw_value else '')
    if not stripped:
        return '', ''

    normalized_code, description = _extract_code_description_pair(stripped, normalizer)
    if normalized_code:
        return normalized_code, description or stripped
    return stripped, stripped


def _apply_opportunity_sorting(qs, sort_key, sort_dir):
    """Apply a safe, user-facing sort to the opportunity queryset."""
    descending = sort_dir == "desc"

    if sort_key == "title":
        return qs.order_by(
            Lower("title").desc() if descending else Lower("title").asc(),
            Lower("solicitation_number").desc() if descending else Lower("solicitation_number").asc(),
            OrderBy(F("posted_date"), descending=True, nulls_last=True),
        )

    if sort_key == "response":
        return qs.order_by(
            OrderBy(F("response_date"), descending=descending, nulls_last=True),
            OrderBy(F("posted_date"), descending=True, nulls_last=True),
        )

    if sort_key == "type":
        return qs.order_by(
            Lower("type").desc() if descending else Lower("type").asc(),
            Lower("base_type").desc() if descending else Lower("base_type").asc(),
            OrderBy(F("posted_date"), descending=True, nulls_last=True),
        )

    if sort_key == "department":
        return qs.order_by(
            Lower("department").desc() if descending else Lower("department").asc(),
            Lower("office").desc() if descending else Lower("office").asc(),
            Lower("sub_office").desc() if descending else Lower("sub_office").asc(),
            OrderBy(F("posted_date"), descending=True, nulls_last=True),
        )

    if sort_key == "naics":
        return qs.order_by(
            Lower("naics_code").desc() if descending else Lower("naics_code").asc(),
            Lower("title").desc() if descending else Lower("title").asc(),
            OrderBy(F("posted_date"), descending=True, nulls_last=True),
        )

    if sort_key == "psc":
        return qs.order_by(
            Lower("product_service_code").desc() if descending else Lower("product_service_code").asc(),
            Lower("title").desc() if descending else Lower("title").asc(),
            OrderBy(F("posted_date"), descending=True, nulls_last=True),
        )

    return qs.order_by(
        OrderBy(F("posted_date"), descending=descending, nulls_last=True),
        OrderBy(F("fetched_at"), descending=True, nulls_last=True),
    )

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
    query = request.GET.get("q", "").strip()
    page_number = request.GET.get("page", 1)
    title_filter = request.GET.get("title", "").strip()
    posted_from_value = request.GET.get("posted_from", "").strip()
    posted_to_value = request.GET.get("posted_to", "").strip()
    response_from_value = request.GET.get("response_from", "").strip()
    response_to_value = request.GET.get("response_to", "").strip()
    type_filter = request.GET.get("type", "").strip()
    department_filter = request.GET.get("department", "").strip()
    naics_filter = request.GET.get("naics", "").strip()
    psc_filter = request.GET.get("psc", "").strip()
    requested_sort = request.GET.get("sort", "posted").strip().lower()
    sort_key = requested_sort if requested_sort in OPPORTUNITY_SORT_DEFAULTS else "posted"
    requested_dir = request.GET.get("dir", OPPORTUNITY_SORT_DEFAULTS[sort_key]).strip().lower()
    sort_dir = requested_dir if requested_dir in {"asc", "desc"} else OPPORTUNITY_SORT_DEFAULTS[sort_key]

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
        redirect_query = _update_querystring(
            request.GET,
            updates={"fetch": None, "page": None},
        )
        url = request.path
        if redirect_query:
            url += f"?{redirect_query}"

        return redirect(url)

    # Display saved opportunities (Local Search)
    qs = SamGovOpportunity.objects.all()

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

    type_options = list(
        qs.exclude(type__isnull=True)
        .exclude(type__exact="")
        .order_by("type")
        .values_list("type", flat=True)
        .distinct()
    )
    naics_lookup_options = list(NAICSCode.objects.order_by("code").values_list("code", "description"))
    psc_lookup_options = list(PSCCode.objects.order_by("code").values_list("code", "description"))

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

    if title_filter:
        qs = qs.filter(
            Q(title__icontains=title_filter)
            | Q(solicitation_number__icontains=title_filter)
        )

    posted_from = parse_date(posted_from_value) if posted_from_value else None
    posted_to = parse_date(posted_to_value) if posted_to_value else None
    response_from = parse_date(response_from_value) if response_from_value else None
    response_to = parse_date(response_to_value) if response_to_value else None

    if posted_from:
        qs = qs.filter(posted_date__gte=posted_from)
    if posted_to:
        qs = qs.filter(posted_date__lte=posted_to)
    if response_from:
        qs = qs.filter(response_date__gte=response_from)
    if response_to:
        qs = qs.filter(response_date__lte=response_to)

    if type_filter:
        qs = qs.filter(type__iexact=type_filter)

    if department_filter:
        qs = qs.filter(
            Q(department__icontains=department_filter)
            | Q(office__icontains=department_filter)
            | Q(sub_office__icontains=department_filter)
        )

    if naics_filter:
        naics_filter_value, naics_filter_text = _normalize_lookup_filter(
            naics_filter,
            _normalize_naics_code,
        )
        qs = qs.filter(
            Q(naics_code__icontains=naics_filter_value)
            | Q(naics_codes__icontains=naics_filter_value)
            | Q(raw_response__icontains=naics_filter_value)
            | Q(raw_response__icontains=naics_filter_text)
        )

    if psc_filter:
        psc_filter_value, psc_filter_text = _normalize_lookup_filter(
            psc_filter,
            _normalize_psc_code,
        )
        qs = qs.filter(
            Q(product_service_code__icontains=psc_filter_value)
            | Q(raw_response__icontains=psc_filter_value)
            | Q(raw_response__icontains=psc_filter_text)
        )

    qs = _apply_opportunity_sorting(qs, sort_key, sort_dir)

    sort_urls = {}
    for candidate_sort, default_dir in OPPORTUNITY_SORT_DEFAULTS.items():
        next_dir = default_dir
        if candidate_sort == sort_key:
            next_dir = "desc" if sort_dir == "asc" else "asc"
        query_string = _update_querystring(
            request.GET,
            updates={"sort": candidate_sort, "dir": next_dir, "page": None, "fetch": None},
        )
        sort_urls[candidate_sort] = f"{request.path}?{query_string}" if query_string else request.path

    page_query = _update_querystring(
        request.GET,
        updates={"page": None, "fetch": None},
    )

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(page_number)

    for opp in page_obj.object_list:
        opp.display_ui_link = _build_opportunity_ui_link(
            solicitation_number=opp.solicitation_number or '',
            api_ui_link=opp.ui_link or '',
        )
        opp.naics_display = _resolve_naics_display(opp)
        opp.psc_display = _resolve_psc_display(opp)
        opp.awardee_display = _resolve_awardee_display(opp)

    return render(request, "tracker/opportunities.html", {
        "page_obj": page_obj,
        "query": query,
        "filter_values": {
            "title": title_filter,
            "posted_from": posted_from_value,
            "posted_to": posted_to_value,
            "response_from": response_from_value,
            "response_to": response_to_value,
            "type": type_filter,
            "department": department_filter,
            "naics": naics_filter,
            "psc": psc_filter,
        },
        "type_options": type_options,
        "naics_lookup_options": naics_lookup_options,
        "psc_lookup_options": psc_lookup_options,
        "sort_key": sort_key,
        "sort_dir": sort_dir,
        "sort_urls": sort_urls,
        "page_query": page_query,
        "search_preserved_params": _query_items(request.GET, exclude={"q", "page", "fetch"}),
        "fetch_preserved_params": _query_items(request.GET, exclude={"page", "fetch"}),
        "column_filter_preserved_params": _query_items(
            request.GET,
            exclude={
                "title",
                "posted_from",
                "posted_to",
                "response_from",
                "response_to",
                "type",
                "department",
                "naics",
                "psc",
                "page",
                "fetch",
            },
        ),
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


def _normalize_psc_code(raw_value):
    """Normalize a PSC value to a 4-character alphanumeric code when possible."""
    if not raw_value:
        return raw_value
    stripped = str(raw_value).strip()
    match = re.match(r'^([A-Za-z0-9]{4})\b', stripped)
    if match:
        return match.group(1).upper()
    exact = PSCCode.objects.filter(description__iexact=stripped).first()
    if exact:
        return exact.code
    partial = PSCCode.objects.filter(description__icontains=stripped[:40]).first()
    if partial:
        return partial.code
    return stripped


def _extract_code_description_pair(raw_value, normalizer):
    """Split a raw code/description string into normalized code plus display description."""
    stripped = (str(raw_value).strip() if raw_value else '')
    if not stripped:
        return '', ''
    normalized_code = normalizer(stripped) or ''
    description = ''
    if normalized_code and stripped != normalized_code:
        description = re.sub(r'^[A-Za-z0-9]{4,8}\s*[-–:]\s*', '', stripped).strip()
        if not description or description == normalized_code:
            description = ''
        elif description == stripped:
            # Entire raw value appears to be a description rather than code + description.
            description = stripped
    elif not normalized_code:
        description = stripped
    return normalized_code, description


def _extract_candidates(payload):
    """Return flattened candidate code/description values from SAM.gov payload fragments."""
    candidates = []
    if not payload:
        return candidates
    if isinstance(payload, dict):
        code = payload.get('code') or payload.get('naicsCode') or payload.get('classificationCode') or payload.get('pscCode') or payload.get('psc')
        description = payload.get('description') or payload.get('title') or payload.get('name') or payload.get('descriptionText')
        if code or description:
            candidates.append((code or '', description or ''))
    elif isinstance(payload, list):
        for item in payload:
            candidates.extend(_extract_candidates(item))
    elif isinstance(payload, str):
        candidates.append((payload, ''))
    return candidates


def _resolve_naics_display(opp):
    """Build a stable NAICS display payload with code, description, and ignore value."""
    code, description = _extract_code_description_pair(opp.naics_code, _normalize_naics_code)

    sources = []
    if opp.naics_codes:
        sources.extend(_extract_candidates(opp.naics_codes))
    if isinstance(opp.raw_response, dict):
        sources.extend(_extract_candidates(opp.raw_response.get('naicsCodes')))
        sources.extend(_extract_candidates(opp.raw_response.get('naicsCode')))
        sources.extend(_extract_candidates(opp.raw_response.get('naics')))

    for candidate_code, candidate_description in sources:
        normalized_candidate = _normalize_naics_code(candidate_code or candidate_description)
        if not code and normalized_candidate:
            code = normalized_candidate
        if not description and candidate_description:
            description = str(candidate_description).strip()
        if code and description:
            break

    if code and not description:
        match = NAICSCode.objects.filter(code=code).first()
        if match:
            description = match.description

    if not code and description:
        code = _normalize_naics_code(description)
        if code == description:
            code = ''

    return {
        'code': code or '',
        'description': description or '',
        'ignore_value': code or '',
    }


def _resolve_psc_display(opp):
    """Build a stable PSC display payload with code, description, and ignore value."""
    code, description = _extract_code_description_pair(opp.product_service_code, _normalize_psc_code)

    raw_response = opp.raw_response if isinstance(opp.raw_response, dict) else {}
    sources = []
    for key in (
        'classificationCode',
        'pscCode',
        'psc',
        'classification',
    ):
        sources.extend(_extract_candidates(raw_response.get(key)))

    description_candidates = [
        raw_response.get('classificationCodeTitle'),
        raw_response.get('classificationTitle'),
        raw_response.get('pscTitle'),
        raw_response.get('pscDescription'),
        raw_response.get('productServiceCodeDescription'),
        raw_response.get('classificationCodeDescription'),
    ]
    for candidate_description in description_candidates:
        if candidate_description:
            sources.append(('', candidate_description))

    for candidate_code, candidate_description in sources:
        normalized_candidate = _normalize_psc_code(candidate_code or candidate_description)
        if not code and normalized_candidate:
            code = normalized_candidate
        if not description and candidate_description:
            description = str(candidate_description).strip()
        if code and description:
            break

    if code and not description:
        match = PSCCode.objects.filter(code=code).first()
        if match:
            description = match.description

    if not code and description:
        code = _normalize_psc_code(description)
        if code == description:
            code = ''

    return {
        'code': code or '',
        'description': description or '',
        'ignore_value': code or '',
    }


def _resolve_awardee_display(opp):
    """Extract awarded contractor name and UEI for award notices and link to Company when possible."""
    payloads = []
    if isinstance(opp.award, dict):
        payloads.append(opp.award)
    if isinstance(opp.raw_response, dict):
        payloads.append(opp.raw_response.get('award') or {})
        payloads.append(opp.raw_response)
        nested_raw_response = opp.raw_response.get('raw_response')
        if isinstance(nested_raw_response, dict):
            payloads.append(nested_raw_response.get('award') or {})
            payloads.append(nested_raw_response)

    contractor_name = ''
    uei = ''
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        contractor_name = contractor_name or (
            payload.get('awardee')
            or payload.get('awardeeName')
            or payload.get('awardeeLegalBusinessName')
            or payload.get('legalBusinessName')
            or payload.get('Legal Business Name')
            or payload.get('recipientName')
            or payload.get('Recipient Name')
            or payload.get('vendorName')
            or payload.get('Vendor Name')
            or payload.get('companyName')
            or payload.get('organizationName')
            or payload.get('Organization Name')
            or ''
        )
        uei = uei or (
            payload.get('uei')
            or payload.get('uniqueEntityId')
            or payload.get('Unique Entity ID')
            or payload.get('awardeeUei')
            or payload.get('recipientUei')
            or payload.get('recipientUEI')
            or payload.get('vendorUei')
            or payload.get('organizationUei')
            or ''
        )
        if contractor_name and uei:
            break

    contractor_name = (str(contractor_name).strip() if contractor_name else '')
    uei = (str(uei).strip() if uei else '')

    company = None
    if uei:
        company = Company.objects.filter(uei__iexact=uei).only('id', 'name').first()
    if not company and contractor_name:
        company = Company.objects.filter(name__iexact=contractor_name).only('id', 'name').first()

    return {
        'name': contractor_name,
        'uei': uei,
        'company': company,
    }


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
                "product_service_code": _normalize_psc_code(
                    data.get("classificationCode") or data.get("pscCode") or data.get("psc") or ""
                ),
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
