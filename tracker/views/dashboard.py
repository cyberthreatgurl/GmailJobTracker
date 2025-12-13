"""Dashboard views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Q, Count
from django.db.models.functions import Lower, TruncDate
from django.shortcuts import render
from django.utils.timezone import now
from tracker.models import Company, Message, ThreadTracking, IngestionStats, UnresolvedCompany
from tracker.views.helpers import extract_body_content, build_sidebar_context


@login_required
def dashboard(request):
    """Render the main dashboard with recent messages, threaded conversations, and summary stats."""
    # Helper no longer needed; extract_body_content used instead
    # def clean_html(raw_html):
    #     soup = BeautifulSoup(raw_html, "html.parser")
    #     for tag in soup(["script", "style", "noscript"]):
    #         tag.decompose()
    #     return str(soup)

    Company.objects.count()
    companies_list = Company.objects.all()
    unresolved_companies = UnresolvedCompany.objects.filter(reviewed=False).order_by(
        "-timestamp"
    )[:50]

    # Handle company filter
    selected_company = None
    company_filter = request.GET.get("company")
    if company_filter:
        try:
            selected_company = Company.objects.get(id=int(company_filter))
        except (Company.DoesNotExist, ValueError):
            selected_company = None

    company_filter_id = selected_company.id if selected_company else None

    # Get all companies for dropdown (excluding headhunters)
    all_companies = Company.objects.exclude(status="headhunter").order_by(Lower("name"))

    # Sidebar metrics will be populated via build_sidebar_context()

    # Load headhunter domains once for dashboard-level filtering
    headhunter_domains = []
    try:
        companies_path = Path("json/companies.json")
        if companies_path.exists():
            with open(companies_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                headhunter_domains = [
                    d.strip().lower()
                    for d in data.get("headhunter_domains", [])
                    if d and isinstance(d, str)
                ]
    except Exception:
        headhunter_domains = []

    # First-time flag will be added to ctx near render

    # ✅ Recent messages with company preloaded
    messages = Message.objects.select_related("company").order_by("-timestamp")[:100]
    for msg in messages:
        raw_html = msg.body or ""
        msg.cleaned_body_html = extract_body_content(raw_html)

    # ✅ Group messages by thread_id with company preloaded
    threads = defaultdict(list)
    seen = set()

    for msg in Message.objects.select_related("company").order_by(
        "thread_id", "timestamp"
    ):
        if msg.msg_id not in seen:
            threads[msg.thread_id].append(msg)
            seen.add(msg.msg_id)

    # ✅ Filter to threads with >1 message, then sort and slice
    thread_list = sorted(
        [(tid, msgs) for tid, msgs in threads.items() if len(msgs) > 1],
        key=lambda t: t[1][-1].timestamp,
        reverse=True,
    )[:50]

    #  Ingestion stats
    latest_stats = IngestionStats.objects.order_by("-date").first()
    ingested_today = latest_stats.total_inserted if latest_stats else 0
    ignored_today = latest_stats.total_ignored if latest_stats else 0
    skipped_today = latest_stats.total_skipped if latest_stats else 0

    # Ingestion plot: start at earliest activity date
    earliest_stat = IngestionStats.objects.order_by("date").first()
    if earliest_stat:
        start_date = earliest_stat.date
        end_date = now().date()
        num_days = (end_date - start_date).days + 1
        date_list = [start_date + timedelta(days=i) for i in range(num_days)]
        stats_qs = IngestionStats.objects.filter(date__gte=start_date).order_by("date")
        stats_map = {s.date: s for s in stats_qs}
        chart_labels = [d.strftime("%Y-%m-%d") for d in date_list]
        chart_inserted = [
            stats_map.get(d, None).total_inserted if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_skipped = [
            stats_map.get(d, None).total_skipped if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_ignored = [
            stats_map.get(d, None).total_ignored if stats_map.get(d, None) else 0
            for d in date_list
        ]
    else:
        chart_labels = []
        chart_inserted = []
        chart_skipped = []
        chart_ignored = []

    # Multi-line chart: daily totals for rejections, applications, interviews, total
    # Use earliest non-null of sent_date, rejection_date, or interview_date so standalone
    # rejections/interviews (without a sent_date) still show up on the chart
    from django.db.models import Min

    date_floor = ThreadTracking.objects.aggregate(
        min_sent=Min("sent_date"),
        min_rej=Min("rejection_date"),
        min_int=Min("interview_date"),
    )
    # Pick the earliest non-null among the three
    non_null_dates = [
        d
        for d in [
            date_floor.get("min_sent"),
            date_floor.get("min_rej"),
            date_floor.get("min_int"),
        ]
        if d
    ]
    # Also include earliest message timestamp so message-only events are visible
    msg_floor = Message.objects.aggregate(min_ts=Min("timestamp")).get("min_ts")
    if msg_floor:
        try:
            non_null_dates.append(msg_floor.date())
        except Exception:
            pass
    app_start_date = min(non_null_dates) if non_null_dates else None
    # Check for REPORTING_DEFAULT_START_DATE in env
    env_start_date = os.environ.get("REPORTING_DEFAULT_START_DATE")
    reporting_default_start_date = None
    if env_start_date:
        try:
            # Accept YYYY-MM-DD only
            reporting_default_start_date = datetime.strptime(
                env_start_date.strip().replace('"', ""), "%Y-%m-%d"
            ).date()
        except Exception:
            reporting_default_start_date = None
    # Use the later of the two (env or earliest_app)
    if reporting_default_start_date and app_start_date:
        if reporting_default_start_date > app_start_date:
            app_start_date = reporting_default_start_date
    elif reporting_default_start_date:
        app_start_date = reporting_default_start_date

    # Load plot series config from JSON file and validate

    from tracker.models import MessageLabel

    def is_valid_color(color):
        # Accept #RRGGBB, #RGB, or valid CSS color names
        if re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", color):
            return True
        css_colors = {
            "blue",
            "green",
            "yellow",
            "gray",
            "grey",
            "black",
            "white",
            "orange",
            "purple",
            "pink",
            "brown",
            "teal",
            "lime",
            "indigo",
            "violet",
            "gold",
            "silver",
        }
        return color.lower() in css_colors

    plot_series_config = []
    try:
        with open("json/plot_series.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        # If MessageLabel table has entries, validate against it; otherwise accept config as-is
        allowed_labels = set(MessageLabel.objects.values_list("label", flat=True))
        for entry in config:
            label = entry.get("label")
            display_name = entry.get("display_name")
            color = entry.get("color")
            # Validate label
            if allowed_labels and label not in allowed_labels:
                # Skip only when we have a whitelist defined in DB
                continue
            # Validate color
            if not is_valid_color(color):
                color = "#2563eb"  # fallback to default
            plot_series_config.append(
                {
                    "key": label,  # Add key field for chart logic
                    "label": label,
                    "display_name": display_name or label,
                    "color": color,
                    "ml_label": label,  # use label as ml_label for consistency
                }
            )
    except Exception:
        # Error in label processing, skip silently
        # fallback to hardcoded config if error
        plot_series_config = [
            {
                "label": "application",
                "display_name": "Application",
                "color": "#2563eb",
                "ml_label": "application",
            },
            {
                "label": "interview",
                "display_name": "Interview",
                "color": "#22c55e",
                "ml_label": "interview",
            },
            {
                "label": "rejected",
                "display_name": "Rejected",
                "color": "#ef4444",
                "ml_label": "rejected",
            },
        ]

    # Now build date list and identify headhunter companies for exclusion
    if app_start_date:
        app_end_date = now().date()
        app_num_days = (app_end_date - app_start_date).days + 1
        app_date_list = [
            app_start_date + timedelta(days=i) for i in range(app_num_days)
        ]
        # Determine headhunter companies once (by domain, sender, or explicit label)
        hh_companies = []
        if headhunter_domains:
            hh_company_q = Q()
            for d in headhunter_domains:
                # Company queryset: use direct field name
                hh_company_q |= Q(domain__iendswith=d)
            msg_hh_q = Q()
            for d in headhunter_domains:
                # Traverse to related messages via reverse FK 'message'
                msg_hh_q |= Q(message__sender__icontains=f"@{d}")
            hh_companies = (
                Company.objects.filter(
                    hh_company_q | msg_hh_q | Q(message__ml_label="head_hunter")
                )
                .distinct()
                .values_list("id", flat=True)
            )
            hh_companies = list(hh_companies)
    else:
        app_date_list = []
        hh_companies = []

    # Build chart data dynamically based on configured series
    chart_series_data = []
    msg_qs = (
        Message.objects.filter(timestamp__date__gte=app_start_date)
        if app_start_date
        else Message.objects.none()
    )
    # Exclude user's own messages from message-based series
    user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()
    if user_email:
        msg_qs = msg_qs.exclude(sender__icontains=user_email)
    if company_filter_id:
        msg_qs = msg_qs.filter(company_id=company_filter_id)

    for series in plot_series_config:
        ml_label = series["ml_label"]
        # Check if this is an application-based series or message-based series
        if ml_label == "job_application":
            # Applications per day - use Message table for accuracy (same as sidebar)
            # Count distinct companies with job_application messages per day
            apps_msg_q = Message.objects.filter(
                ml_label__in=["job_application", "application"],
                company__isnull=False,
            )
            if app_start_date:
                apps_msg_q = apps_msg_q.filter(timestamp__date__gte=app_start_date)
            # Exclude user's own messages
            user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()
            if user_email:
                apps_msg_q = apps_msg_q.exclude(sender__icontains=user_email)
            if hh_companies:
                apps_msg_q = apps_msg_q.exclude(company_id__in=hh_companies)
            if company_filter_id:
                apps_msg_q = apps_msg_q.filter(company_id=company_filter_id)
            # Exclude headhunter domain senders
            if headhunter_domains:
                msg_hh_q = Q()
                for d in headhunter_domains:
                    msg_hh_q |= Q(sender__icontains=f"@{d}")
                apps_msg_q = apps_msg_q.exclude(msg_hh_q)
            
            # Group by day and count total application messages
            apps_by_day = (
                apps_msg_q.annotate(day=TruncDate("timestamp"))
                .values("day")
                .annotate(count=Count("id"))
            )
            # Map application count per day
            apps_map = {r["day"]: r["count"] for r in apps_by_day}
            
            data = [apps_map.get(d, 0) for d in app_date_list]
        elif ml_label == "rejected":
            # Rejections per day: combine Application-based and Message-based (fallback) counts
            # 1) Applications by rejection_date
            rejs_q = ThreadTracking.objects.filter(rejection_date__isnull=False)
            if app_start_date:
                rejs_q = rejs_q.filter(rejection_date__gte=app_start_date)
            if hh_companies:
                rejs_q = rejs_q.exclude(company_id__in=hh_companies)
            if company_filter_id:
                rejs_q = rejs_q.filter(company_id=company_filter_id)
            rejs_by_day = rejs_q.values("rejection_date").annotate(
                count=models.Count("id")
            )
            app_rejs_map = {r["rejection_date"]: r["count"] for r in rejs_by_day}

            # 2) Messages labeled rejected/rejection (exclude those whose thread has an Application)
            app_threads = list(
                ThreadTracking.objects.filter(rejection_date__isnull=False).values_list(
                    "thread_id", flat=True
                )
            )
            msg_rejs_q = Message.objects.filter(
                ml_label__in=["rejected", "rejection"],
            )
            if app_start_date:
                msg_rejs_q = msg_rejs_q.filter(timestamp__date__gte=app_start_date)
            user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()
            if user_email:
                msg_rejs_q = msg_rejs_q.exclude(sender__icontains=user_email)
            # Exclude headhunter domains for messages
            if headhunter_domains:
                msg_hh_q = Q()
                for d in headhunter_domains:
                    msg_hh_q |= Q(sender__icontains=f"@{d}")
                msg_rejs_q = msg_rejs_q.exclude(msg_hh_q)
            # Exclude messages in threads already represented by Applications
            if app_threads:
                msg_rejs_q = msg_rejs_q.exclude(thread_id__in=app_threads)
            if company_filter_id:
                msg_rejs_q = msg_rejs_q.filter(company_id=company_filter_id)
            msg_rejs_by_day = (
                msg_rejs_q.annotate(day=TruncDate("timestamp"))
                .values("day")
                .annotate(count=models.Count("id"))
            )
            msg_rejs_map = {r["day"]: r["count"] for r in msg_rejs_by_day}

            # 3) Combine (sum) per date
            combined = {}
            for d in app_date_list:
                combined[d] = app_rejs_map.get(d, 0) + msg_rejs_map.get(d, 0)
            data = [combined[d] for d in app_date_list]
        elif ml_label in ("interview_invite", "interview"):
            # Interviews per day
            ints_q = ThreadTracking.objects.filter(interview_date__isnull=False)
            if app_start_date:
                ints_q = ints_q.filter(interview_date__gte=app_start_date)
            if hh_companies:
                ints_q = ints_q.exclude(company_id__in=hh_companies)
            if company_filter_id:
                ints_q = ints_q.filter(company_id=company_filter_id)
            ints_by_day = ints_q.values("interview_date").annotate(
                count=models.Count("id")
            )
            ints_map = {r["interview_date"]: r["count"] for r in ints_by_day}
            data = [ints_map.get(d, 0) for d in app_date_list]
        else:
            # Message-based series (referral, head_hunter, noise, etc.)
            msgs_by_day = (
                msg_qs.filter(ml_label=ml_label)
                .extra(select={"day": "date(timestamp)"})
                .values("day")
                .annotate(count=models.Count("id"))
            )
            msgs_map = {r["day"]: r["count"] for r in msgs_by_day}
            data = [msgs_map.get(d.strftime("%Y-%m-%d"), 0) for d in app_date_list]

        chart_series_data.append(
            {
                "key": series["key"],
                "label": series["label"],
                "color": series["color"],
                "data": data,
            }
        )

    # Defensive: ensure all chart arrays exist
    chart_activity_labels = (
        [d.strftime("%Y-%m-%d") for d in app_date_list] if app_date_list else []
    )
    if not chart_labels:
        chart_labels = []
        chart_inserted = []
        chart_skipped = []
        chart_ignored = []
    if not chart_activity_labels:
        chart_activity_labels = []
        chart_series_data = []

    # ✅ Company breakdown by status for the selected time period
    # This will be filtered client-side based on the chart's date range
    # Get all applications with their company names and dates

    # Build headhunter exclusion list first (needed for all queries)
    hh_company_list = []
    if headhunter_domains:
        hh_company_q = Q()
        for d in headhunter_domains:
            # Company queryset: use direct field name
            hh_company_q |= Q(domain__iendswith=d)
        msg_hh_q = Q()
        for d in headhunter_domains:
            # Traverse to related messages via reverse FK 'message'
            msg_hh_q |= Q(message__sender__icontains=f"@{d}")
        hh_companies = (
            Company.objects.filter(
                hh_company_q | msg_hh_q | Q(message__ml_label="head_hunter")
            )
            .distinct()
            .values_list("id", flat=True)
        )
        if hh_companies:
            hh_company_list = list(hh_companies)

    # Rejections: Combine Application-based AND Message-based (for standalone rejection emails)
    # 1) Application-based rejections
    rejection_companies_qs = (
        ThreadTracking.objects.filter(
            rejection_date__isnull=False, company__isnull=False
        )
        .exclude(ml_label="noise")  # Exclude noise from metrics
        .select_related("company")
        .values("company_id", "company__name", "rejection_date")
    )
    if hh_company_list:
        rejection_companies_qs = rejection_companies_qs.exclude(
            company_id__in=hh_company_list
        )
    if company_filter_id:
        rejection_companies_qs = rejection_companies_qs.filter(
            company_id=company_filter_id
        )

    # 2) Message-based rejections (messages without corresponding Application.rejection_date)
    msg_rejections_qs = Message.objects.filter(
        ml_label__in=["rejected", "rejection"], company__isnull=False
    )
    if user_email:
        msg_rejections_qs = msg_rejections_qs.exclude(sender__icontains=user_email)
    if headhunter_domains:
        msg_hh_sender_q = Q()
        for d in headhunter_domains:
            msg_hh_sender_q |= Q(sender__icontains=f"@{d}")
        msg_rejections_qs = msg_rejections_qs.exclude(msg_hh_sender_q)
    if hh_company_list:
        msg_rejections_qs = msg_rejections_qs.exclude(company_id__in=hh_company_list)
    if company_filter_id:
        msg_rejections_qs = msg_rejections_qs.filter(company_id=company_filter_id)

    # Get message-based rejections with company info
    msg_rejection_data = msg_rejections_qs.select_related("company").values(
        "company_id", "company__name", "timestamp"
    )

    # Use Message table directly for application companies (same as chart and sidebar)
    # This ensures consistency across all dashboard metrics
    application_companies_qs = (
        Message.objects.filter(
            ml_label__in=["job_application", "application"],
            company__isnull=False,
        )
        .select_related("company")
        .annotate(sent_date=TruncDate("timestamp"))
        .values("company_id", "company__name", "sent_date")
        .order_by("-sent_date")
    )
    # Exclude user's own messages
    user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()
    if user_email:
        application_companies_qs = application_companies_qs.exclude(
            sender__icontains=user_email
        )
    # Exclude headhunter companies
    if hh_company_list:
        application_companies_qs = application_companies_qs.exclude(
            company_id__in=hh_company_list
        )
    # Exclude headhunter domain senders
    if headhunter_domains:
        msg_hh_q = Q()
        for d in headhunter_domains:
            msg_hh_q |= Q(sender__icontains=f"@{d}")
        application_companies_qs = application_companies_qs.exclude(msg_hh_q)
    if company_filter_id:
        application_companies_qs = application_companies_qs.filter(
            company_id=company_filter_id
        )

    ghosted_companies_qs = (
        ThreadTracking.objects.filter(
            Q(status="ghosted") | Q(ml_label="ghosted"), company__isnull=False
        )
        .exclude(ml_label="noise")  # Exclude noise from metrics
        .select_related("company")
        .values("company_id", "company__name", "sent_date")
        .order_by("-sent_date")
    )
    if hh_company_list:
        ghosted_companies_qs = ghosted_companies_qs.exclude(
            company_id__in=hh_company_list
        )
    if company_filter_id:
        ghosted_companies_qs = ghosted_companies_qs.filter(company_id=company_filter_id)

    # Convert date objects to strings for JSON serialization

    # Combine Application-based and Message-based rejections
    rejection_companies = []
    # Add Application-based rejections
    for item in rejection_companies_qs:
        rejection_companies.append(
            {
                "company_id": item["company_id"],
                "company__name": item["company__name"],
                "rejection_date": item["rejection_date"].strftime("%Y-%m-%d"),
            }
        )
    # Add Message-based rejections (using timestamp as rejection_date)
    for item in msg_rejection_data:
        rejection_companies.append(
            {
                "company_id": item["company_id"],
                "company__name": item["company__name"],
                "rejection_date": item["timestamp"].strftime("%Y-%m-%d"),
            }
        )

    application_companies = [
        {
            "company_id": item["company_id"],
            "company__name": item["company__name"],
            "sent_date": item["sent_date"].strftime("%Y-%m-%d"),
        }
        for item in application_companies_qs
    ]

    # Interviews: combine Application-based (interview_date) AND Message-based (interview_invite)
    # 1) Application-based interviews (scheduled interview_date)
    interview_companies_qs = (
        ThreadTracking.objects.filter(
            interview_date__isnull=False,
            company__isnull=False,
        )
        .exclude(ml_label="noise")
        .select_related("company")
        .values("company_id", "company__name", "interview_date")
        .order_by("-interview_date")
    )
    if hh_company_list:
        interview_companies_qs = interview_companies_qs.exclude(
            company_id__in=hh_company_list
        )
    if company_filter_id:
        interview_companies_qs = interview_companies_qs.filter(
            company_id=company_filter_id
        )

    # Use a dict to track the earliest interview per company (deduplicate by company_id)
    interview_by_company = {}
    
    for item in interview_companies_qs:
        company_id = item["company_id"]
        interview_date = item["interview_date"]
        # Keep the EARLIEST interview_date per company (first contact)
        if company_id not in interview_by_company or interview_date < interview_by_company[company_id]["interview_date"]:
            interview_by_company[company_id] = {
                "company_id": company_id,
                "company__name": item["company__name"],
                "interview_date": interview_date,
            }

    # 2) Message-based interview invites (only for companies WITHOUT a ThreadTracking interview_date)
    # This prevents double-counting: if company has ThreadTracking.interview_date, don't add message-based entry
    # Build a set of company_ids that already have interview_date in ThreadTracking
    tracked_companies = set(interview_by_company.keys())
    
    # Get all interview messages (support both 'interview_invite' and 'interview')
    msg_interviews_qs = Message.objects.filter(
        ml_label__in=["interview_invite", "interview"], company__isnull=False
    ).select_related('company')
    
    if user_email:
        msg_interviews_qs = msg_interviews_qs.exclude(sender__icontains=user_email)
    if headhunter_domains:
        msg_hh_sender_q = Q()
        for d in headhunter_domains:
            msg_hh_sender_q |= Q(sender__icontains=f"@{d}")
        msg_interviews_qs = msg_interviews_qs.exclude(msg_hh_sender_q)
    if hh_company_list:
        msg_interviews_qs = msg_interviews_qs.exclude(company_id__in=hh_company_list)
    if company_filter_id:
        msg_interviews_qs = msg_interviews_qs.filter(company_id=company_filter_id)

    # Add message-based interviews, keeping only the most recent per company
    # Skip companies that already have ThreadTracking interview_date
    for msg in msg_interviews_qs:
        company_id = msg.company_id
        msg_date = msg.timestamp.date()
        
        # Skip if this company already has a ThreadTracking interview
        if company_id in tracked_companies:
            continue
            
        # Keep the EARLIEST message-based interview per company (first contact)
        if company_id not in interview_by_company or msg_date < interview_by_company[company_id]["interview_date"]:
            interview_by_company[company_id] = {
                "company_id": company_id,
                "company__name": msg.company.name,
                "interview_date": msg_date,
            }

    # Convert to list, format dates as strings
    interview_companies = [
        {
            "company_id": item["company_id"],
            "company__name": item["company__name"],
            "interview_date": item["interview_date"].strftime("%Y-%m-%d") 
                if isinstance(item["interview_date"], date) 
                else str(item["interview_date"]),
        }
        for item in interview_by_company.values()
    ]

    ghosted_companies = [
        {
            "company_id": item["company_id"],
            "company__name": item["company__name"],
            "sent_date": item["sent_date"].strftime("%Y-%m-%d"),
        }
        for item in ghosted_companies_qs
    ]
    
    # Debug logging for ghosted companies
    if len(ghosted_companies) == 0:
        print(f"[DEBUG] Ghosted companies query returned 0 results")
        print(f"[DEBUG] hh_company_list count: {len(hh_company_list) if hh_company_list else 0}")
        print(f"[DEBUG] company_filter_id: {company_filter_id}")
    else:
        print(f"[DEBUG] Found {len(ghosted_companies)} ghosted companies")

    # Convert to JSON strings for template
    rejection_companies_json = json.dumps(rejection_companies)
    application_companies_json = json.dumps(application_companies)
    ghosted_companies_json = json.dumps(ghosted_companies)
    interview_companies_json = json.dumps(interview_companies)

    # Server-side initial fallback lists (unique by company for full available range)
    def unique_by_company(items, id_key="company_id", name_key="company__name"):
        seen = set()
        out = []
        for it in items:
            cid = it.get(id_key)
            cname = it.get(name_key)
            if cid is not None and cid not in seen and cname:
                out.append({"id": cid, "name": cname})
                seen.add(cid)
        # sort by name for a stable display
        out.sort(key=lambda x: (x["name"] or "").lower())
        return out

    initial_rejection_companies = unique_by_company(rejection_companies)
    initial_application_companies = unique_by_company(application_companies)
    initial_ghosted_companies = unique_by_company(ghosted_companies)
    initial_interview_companies = unique_by_company(interview_companies)

    # Cumulative ghosted count (total unique companies currently ghosted)
    ghosted_count = len(initial_ghosted_companies)

    ctx = {
        "companies_list": companies_list,
        "messages": messages,
        "threads": thread_list,
        "latest_stats": latest_stats,
        "chart_labels": chart_labels,
        "chart_inserted": chart_inserted,
        "chart_skipped": chart_skipped,
        "chart_ignored": chart_ignored,
        "chart_activity_labels": chart_activity_labels,
        "chart_series_data": chart_series_data,
        "plot_series_config": plot_series_config,
        "unresolved_companies": unresolved_companies,
        "ingested_today": ingested_today,
        "ignored_today": ignored_today,
        "skipped_today": skipped_today,
        "reporting_default_start_date": (
            reporting_default_start_date.strftime("%Y-%m-%d")
            if reporting_default_start_date
            else ""
        ),
        "rejection_companies_json": rejection_companies_json,
        "application_companies_json": application_companies_json,
        "ghosted_companies_json": ghosted_companies_json,
        "interview_companies_json": interview_companies_json,
        "initial_rejection_companies": initial_rejection_companies,
        "initial_application_companies": initial_application_companies,
        "initial_ghosted_companies": initial_ghosted_companies,
        "initial_interview_companies": initial_interview_companies,
        "ghosted_count": ghosted_count,
        "all_companies": all_companies,
        "selected_company": selected_company,
    }
    # Ensure single source of truth for sidebar cards like Applications This Week
    # First-time user flag: show onboarding modal if no messages exist
    ctx["is_first_time"] = (Message.objects.count() == 0)
    ctx.update(build_sidebar_context())
    return render(request, "tracker/dashboard.html", ctx)


@login_required
def company_threads(request):
    """Show reviewed message threads grouped by subject for a selected company."""
    # Get all reviewed companies (at least one reviewed message)
    reviewed_company_ids = (
        Message.objects.filter(reviewed=True, company__isnull=False)
        .values_list("company_id", flat=True)
        .distinct()
    )
    companies = Company.objects.filter(id__in=reviewed_company_ids).order_by("name")

    selected_company_id = request.GET.get("company")
    selected_company = None
    threads_by_subject = []
    if selected_company_id:
        try:
            selected_company = companies.get(id=selected_company_id)
        except Company.DoesNotExist:
            selected_company = None
        if selected_company:
            # Group messages by subject for this company, only reviewed
            msgs = Message.objects.filter(
                company=selected_company, reviewed=True
            ).order_by("thread_id", "timestamp")
            # subject -> list of threads (each thread is a list of messages)
            threads = defaultdict(list)
            for msg in msgs:
                threads[msg.subject].append(msg)
            # Each subject: list of messages (thread)
            threads_by_subject = [
                {"subject": subj, "messages": thread}
                for subj, thread in threads.items()
            ]

    # Build context and ensure sidebar values come from build_sidebar_context()
    ctx = {
        "company_list": companies,
        "selected_company": selected_company,
        "threads_by_subject": threads_by_subject,
    }
    return render(request, "tracker/company_threads.html", ctx)



@login_required
def metrics(request):
    """Display model metrics, training audit, and ingestion stats visualizations."""
    model_metrics = {}
    training_output = None
    metrics_path = Path("model/model_info.json")
    if metrics_path.exists():
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                model_metrics = json.load(f)
        except Exception:
            model_metrics = {}
    # Optionally, show last training output
    output_path = Path("model/model_audit.json")
    if output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                audit = json.load(f)
                training_output = audit.get("training_output")
        except Exception:
            training_output = None

    # Ingestion stats plot data (same as dashboard)
    earliest_stat = IngestionStats.objects.order_by("date").first()
    if earliest_stat:
        start_date = earliest_stat.date
        end_date = now().date()
        num_days = (end_date - start_date).days + 1
        date_list = [start_date + timedelta(days=i) for i in range(num_days)]
        stats_qs = IngestionStats.objects.filter(date__gte=start_date).order_by("date")
        stats_map = {s.date: s for s in stats_qs}
        chart_labels = [d.strftime("%Y-%m-%d") for d in date_list]
        chart_inserted = [
            stats_map.get(d, None).total_inserted if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_skipped = [
            stats_map.get(d, None).total_skipped if stats_map.get(d, None) else 0
            for d in date_list
        ]
        chart_ignored = [
            stats_map.get(d, None).total_ignored if stats_map.get(d, None) else 0
            for d in date_list
        ]
    else:
        chart_labels = []
        chart_inserted = []
        chart_skipped = []
        chart_ignored = []

    # Categorize labels into real vs extra (company names that need fixing)
    valid_labels = {
        "interview",
        "interview_invite",
        "application",
        "job_application",
        "rejected",
        "offer",
        "noise",
        "referral",
        "head_hunter",
        "ghosted",
        "follow_up",
        "response",
        "unknown",
    }
    label_breakdown = None
    if isinstance(model_metrics, dict) and isinstance(model_metrics.get("labels"), list):
        real_labels = [
            label for label in model_metrics["labels"] if label.lower() in valid_labels
        ]
        extra_labels = [
            label for label in model_metrics["labels"] if label.lower() not in valid_labels
        ]
        label_breakdown = {
            "real_count": len(real_labels),
            "extra_count": len(extra_labels),
            "real_labels": real_labels,
            "extra_labels": extra_labels,
        }

    ctx = {
        "metrics": model_metrics,
        "training_output": training_output,
        "label_breakdown": label_breakdown,
        "chart_labels": chart_labels,
        "chart_inserted": chart_inserted,
        "chart_skipped": chart_skipped,
        "chart_ignored": chart_ignored,
    }
    return render(request, "tracker/metrics.html", ctx)



__all__ = ['dashboard', 'company_threads', 'metrics']
