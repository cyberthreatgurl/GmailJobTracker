"""Django dashboard and admin views for GmailJobTracker.

This module contains:
- Label Rule Debugger UI for testing regex patterns against messages
- Gmail filters import/compare views for managing label rules
- Dashboard views for labeling applications, companies, and metrics
- Maintenance actions (retrain model, re-ingest messages, delete company)

These views operate entirely on local data (SQLite) and integrate with the
ingestion/ML pipeline via helper modules where needed.
"""

# --- Label Rule Debugger ---

import json
import logging
import os
import re
from parser import extract_metadata, parse_raw_message
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models.functions import Coalesce, StrIndex, Substr
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt

from scripts.import_gmail_filters import (
    load_json,
    make_or_pattern,
    sanitize_to_regex_terms,
)

logger = logging.getLogger(__name__)
from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    Value,
    When,
)
from django.db.models.functions import Lower
from django.http import StreamingHttpResponse

# Consolidated shared imports for the entire module to avoid reimports
import html
import subprocess
import sys
from collections import defaultdict

from difflib import HtmlDiff

from bs4 import BeautifulSoup
from gmail_auth import get_gmail_service
from db import PATTERNS_PATH
from tracker.forms import ApplicationEditForm, ManualEntryForm
from tracker.models import (
    Company,
    IngestionStats,
    Message,
    ThreadTracking,
    UnresolvedCompany,
)
from .forms_company import CompanyEditForm


@login_required
def label_rule_debugger(request):
    """
    Web page to upload a raw Gmail message, parse it, and highlight which words/patterns caused it to be sorted to a specific label.
    Shows:
      - Message text (with highlights)
      - Installed rule(s) that fired
      - Words/patterns that matched
    """
    result = None
    error = None
    highlights = []
    matched_label = None
    matched_patterns = []  # list of strings like "<label>: <pattern>"
    matched_labels = []  # unique labels that matched
    message_text = ""
    no_matches = False
    if request.method == "POST":
        pasted = (request.POST.get("pasted_message") or "").strip()
        upload = request.FILES.get("message_file")
        if not pasted and not upload:
            error = "Provide an uploaded file or paste the full message source."
        else:
            try:
                if pasted:
                    raw_text = pasted
                else:
                    raw_text = upload.read().decode("utf-8", errors="replace")
                # Try JSON first
                try:
                    msg_obj = json.loads(raw_text)
                except Exception:
                    msg_obj = raw_text
                # Extract metadata robustly for raw EML or pasted content
                subject = ""
                body = ""
                try:
                    if isinstance(msg_obj, str):
                        meta = parse_raw_message(msg_obj)
                    else:
                        # If JSON provided, we don't have Gmail service here; fallback to EML path
                        meta = parse_raw_message(raw_text)
                    subject = meta.get("subject", "")
                    body = meta.get("body", "")
                except Exception:
                    # naive fallback: split headers/body for EML-like content
                    parts = raw_text.split("\n\n", 1)
                    if parts:
                        headers = parts[0]
                        body = parts[1] if len(parts) > 1 else raw_text
                        for line in headers.splitlines():
                            if line.lower().startswith("subject:"):
                                subject = line.split(":", 1)[1].strip()
                message_text = body or subject
                patterns_path = Path("json/patterns.json")
                patterns = load_json(patterns_path, default={"message_labels": {}})
                msg_labels = patterns.get("message_labels", {})
                
                # Match labels in PRIORITY ORDER (same as rule_label function in parser.py)
                # Stop at the FIRST match to reflect actual ingestion behavior
                # Note: "interview_invite" in patterns.json is stored as "interview"
                # and "job_application" as "application"
                label_priority = [
                    "offer",
                    "head_hunter",
                    "noise",
                    "rejection",
                    "interview",  # Maps to interview_invite
                    "application",  # Maps to job_application
                    "referral",
                    "ghosted",
                    "blank",
                    "other",
                ]
                
                highlights_set = set()
                matched_labels_set = set()
                found_match = False
                
                for label in label_priority:
                    if found_match:
                        break  # Stop after first match
                    
                    rules = msg_labels.get(label, [])
                    for rule in rules:
                        if rule == "None":
                            continue

                        # Use the rule as a standard regex pattern
                        try:
                            # Compile regex with case-insensitive flag
                            pattern = re.compile(rule, re.IGNORECASE)
                            match = pattern.search(message_text)

                            if match:
                                # Found a match! Record it and stop checking
                                matched_patterns.append(f"{label}: {rule}")
                                matched_label = label
                                matched_labels_set.add(label)
                                found_match = True

                                # Extract matched text for highlighting
                                matched_text = match.group(0)
                                highlights_set.add(matched_text)

                                # Also try to extract individual OR alternatives for highlighting
                                # Split on | outside of character classes and groups
                                simple_split = rule.split("|")
                                for alt in simple_split:
                                    clean_alt = alt.strip("()").strip()
                                    if clean_alt:
                                        try:
                                            alt_pattern = re.compile(
                                                clean_alt, re.IGNORECASE
                                            )
                                            alt_match = alt_pattern.search(message_text)
                                            if alt_match:
                                                highlights_set.add(alt_match.group(0))
                                        except:
                                            pass
                                
                                break  # Stop checking rules for this label
                        except re.error as e:
                            # Invalid regex pattern - log but continue
                            print(
                                f"Invalid regex pattern for {label}: {rule} - Error: {e}"
                            )
                            continue

                highlights = sorted(highlights_set, key=lambda s: s.lower())
                matched_labels = sorted(matched_labels_set)
                if not matched_labels:
                    no_matches = True
                # Highlight words in message_text
                # re is now imported globally

                def highlight_text(text, words):
                    for word in set(words):
                        pattern = re.compile(re.escape(word), re.IGNORECASE)
                        text = pattern.sub(
                            lambda m: f'<span style="background:#f59e42;">{m.group(0)}</span>',
                            text,
                        )
                    return text

                message_text = highlight_text(message_text, highlights)
                result = {
                    "subject": subject,
                    "body": body,
                    "matched_label": matched_label,
                    "matched_labels": matched_labels,
                    "matched_patterns": matched_patterns,
                    "highlights": highlights,
                    "no_matches": no_matches,
                }
            except Exception as e:
                error = f"Failed to parse message: {e}"
    ctx = {
        "result": result,
        "error": error,
        "message_text": message_text,
        "highlights": highlights,
        "matched_label": matched_label,
        "matched_labels": matched_labels,
        "matched_patterns": matched_patterns,
        "no_matches": no_matches,
    }
    return render(request, "tracker/label_rule_debugger.html", ctx)


@login_required
def compare_gmail_filters(request):
    """
    Enhanced Gmail filter import page:
    1. Auto-fetch Gmail filters and save to timestamped XML file.
    2. Display filters and installed rules side-by-side.
    3. Highlight differences in installed rules.
    4. Support checkboxes for all/individual filters.
    5. Allow editing and saving installed rules.
    """
    filters = []
    error = None
    gmail_label_prefix = (
        request.POST.get("gmail_label_prefix")
        or request.GET.get("gmail_label_prefix")
        or os.environ.get("GMAIL_ROOT_FILTER_LABEL")
        or os.environ.get("JOB_HUNT_LABEL_PREFIX")
        or "#job-hunt"
    )
    patterns_path = Path("json/patterns.json")
    label_map_path = Path("json/gmail_label_map.json")
    patterns = load_json(patterns_path, default={"message_labels": {}})
    msg_labels = patterns.setdefault("message_labels", {})
    label_map = load_json(label_map_path, default={})

    # 1) Auto-fetch Gmail filters and save to timestamped XML file
    try:
        service = get_gmail_service()
        if not service:
            raise RuntimeError(
                "Failed to initialize Gmail service. Check OAuth credentials in json/."
            )
        prefix = gmail_label_prefix.strip()
        labels_resp = service.users().labels().list(userId="me").execute()
        id_to_name = {
            lab.get("id"): lab.get("name") for lab in labels_resp.get("labels", [])
        }
        # name_to_id unused; kept for potential future use
        filt_resp = service.users().settings().filters().list(userId="me").execute()
        filters_raw = filt_resp.get("filter", []) or []

        # Debug logging
        print(f"🔍 DEBUG: Fetched {len(filters_raw)} Gmail filters")
        print(f"🔍 DEBUG: Using prefix: '{prefix}'")
        print(f"🔍 DEBUG: Total Gmail labels: {len(id_to_name)}")

        # Save to timestamped XML file
        now_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        xml_filename = f"gmail_filters_{now_str}.xml"
        xml_path = Path("json") / xml_filename
        import xml.etree.ElementTree as ET

        root = ET.Element("filters")
        for f in filters_raw:
            entry = ET.SubElement(root, "filter")
            for k, v in f.items():
                sub = ET.SubElement(entry, k)
                sub.text = str(v)
        tree = ET.ElementTree(root)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        print(f"✅ Saved Gmail filters to {xml_path}")
    except Exception as e:
        error = f"Failed to fetch/save Gmail filters: {e}"
        filters_raw = []
        print(f"❌ ERROR: {error}")

    # 2) Display filters and installed rules side-by-side
    diff_engine = HtmlDiff()
    debug_mappings = []  # For debugging: track how each Gmail label maps to internal
    unmapped_labels = []  # Track labels that couldn't be mapped

    filters_checked = 0  # Count how many filters we process
    filters_skipped = 0  # Count how many filters we skip

    print("\n==== DEBUG: All Gmail filter labels fetched from API ====")
    for i, f in enumerate(filters_raw):
        criteria = f.get("criteria", {}) or {}
        action = f.get("action", {}) or {}
        add_ids = action.get("addLabelIds", []) or []
        target_label_names = [id_to_name.get(j, "") for j in add_ids]
        print(f"Filter #{i}: {target_label_names}")
    print("==== END DEBUG FILTER LABELS ====")

    for i, f in enumerate(filters_raw):
        criteria = f.get("criteria", {}) or {}
        action = f.get("action", {}) or {}
        add_ids = action.get("addLabelIds", []) or []
        target_label_names = [id_to_name.get(j, "") for j in add_ids]

        # Debug: show all target labels for this filter
        if target_label_names:
            print(f"🔍 Filter #{i}: labels={target_label_names}, prefix='{prefix}'")

        matched_names = [
            nm
            for nm in target_label_names
            if isinstance(nm, str) and nm.startswith(prefix)
        ]
        if not matched_names:
            filters_skipped += 1
            continue

        filters_checked += 1
        for lname in matched_names:
            gmail_label = lname
            # Always strip the root prefix for display and mapping
            root_prefix = gmail_label_prefix.rstrip("/") + "/"
            display_label = (
                gmail_label[len(root_prefix) :]
                if gmail_label.startswith(root_prefix)
                else gmail_label
            )

            # Debug: show full criteria for this filter
            print(f"   📧 Criteria keys: {list(criteria.keys())}")
            print(f"   📧 Criteria content: {criteria}")

            internal = label_map.get(gmail_label)
            if not internal:
                direct = display_label.strip()
                base_key = direct.lower().split("/")[-1]
                synonyms = {
                    # Map Gmail label suffixes to our internal message_labels keys
                    "rejection": "rejection",
                    "reject": "rejection",
                    "rejected": "rejection",
                    "application": "application",
                    "apply": "application",
                    "interview": "interview",
                    "prescreen": "prescreen",
                    "headhunter": "head_hunter",
                    "head_hunter": "head_hunter",
                    "noise": "noise",
                    "referral": "referral",
                    "offer": "offer",
                    "follow_up": "follow_up",
                    "followup": "follow_up",
                    "response": "response",
                    "ghosted": "ghosted",
                    "other": "other",
                    "ignore": "ignore",
                }
                tentative = synonyms.get(base_key, direct)
                allowed_labels = set(msg_labels.keys()) | {
                    "application",
                    "interview",
                    "rejection",
                    "head_hunter",
                    "noise",
                    "referral",
                    "offer",
                    "follow_up",
                    "response",
                    "ghosted",
                    "other",
                    "ignore",
                }
                internal = tentative if tentative in allowed_labels else None

            # Track mapping for debug display
            mapping_info = {
                "gmail_label": gmail_label,
                "display_label": display_label,
                "base_key": (
                    display_label.lower().split("/")[-1]
                    if not label_map.get(gmail_label)
                    else "(from map)"
                ),
                "internal": internal or "UNMAPPED",
                "source": (
                    "label_map"
                    if label_map.get(gmail_label)
                    else "synonym" if internal else "none"
                ),
            }
            debug_mappings.append(mapping_info)
            if not internal:
                unmapped_labels.append(gmail_label)

            # Gmail rule (raw)
            terms = []
            for key in ("subject", "hasTheWord", "query"):
                raw_value = criteria.get(key, "")
                if raw_value:
                    print(f"   📝 {key}: {raw_value}")
                extracted = sanitize_to_regex_terms(raw_value)
                if extracted:
                    print(f"      → extracted: {extracted}")
                terms += extracted

            print(f"   🔧 Total terms: {len(terms)}")
            gmail_rule = make_or_pattern(terms) or ""
            print(
                f"   📋 Gmail rule result: {gmail_rule[:100] if gmail_rule else '(empty)'}"
            )

            # Installed rule (editable): Only show if label is present in msg_labels
            if internal and internal in msg_labels:
                installed_rule = "\n".join(msg_labels[internal])
            else:
                installed_rule = ""
            # Diff highlight
            diff_html = ""
            if installed_rule and gmail_rule:
                diff_html = diff_engine.make_table(
                    gmail_rule.splitlines(),
                    installed_rule.splitlines(),
                    fromdesc="Gmail Rule",
                    todesc="Installed Rule",
                    context=True,
                    numlines=2,
                )
            filters.append(
                {
                    "label": display_label,
                    "gmail_rule": gmail_rule,
                    "installed_rule": installed_rule,
                    "diff_html": diff_html,
                    "checked": bool(
                        internal and gmail_rule and (gmail_rule not in installed_rule)
                    ),
                }
            )

    # Debug summary
    print(f"📊 Filter processing summary:")
    print(f"   - Total raw filters: {len(filters_raw)}")
    print(f"   - Filters checked: {filters_checked}")
    print(f"   - Filters skipped (no matching prefix): {filters_skipped}")
    print(f"   - Final filters for display: {len(filters)}")
    print(f"   - Debug mappings: {len(debug_mappings)}")
    print(f"   - Unmapped labels: {len(unmapped_labels)}")

    # 3) Handle POST: apply selected filters
    if (
        request.method == "POST"
        and request.POST.get("action") == "apply_selected_filters"
    ):
        updated = 0
        for i, f in enumerate(filters):
            if not request.POST.get(f"update_{i}"):
                continue
            internal = label_map.get(f["label"])
            if not internal:
                continue
            new_rule = request.POST.get(f"installed_pattern_{i}")
            if new_rule:
                msg_labels[internal] = [
                    r.strip() for r in new_rule.splitlines() if r.strip()
                ]
                updated += 1
        with open(patterns_path, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2, ensure_ascii=False)
        messages.success(
            request, f"Imported and updated {updated} filter(s) in patterns.json."
        )
        return redirect("import_gmail_filters_compare")

    ctx = {
        "filters": filters,
        "error": error,
        "gmail_label_prefix": gmail_label_prefix,
        "debug_mappings": debug_mappings,
        "unmapped_labels": unmapped_labels,
    }
    return render(request, "tracker/import_gmail_filters_compare.html", ctx)


# --- Gmail Filters Label Patterns Compare ---
@login_required
def gmail_filters_labels_compare(request):
    """
    Fetch Gmail filter rules via the Gmail API, compare old/new regex patterns for message labels, and allow incremental update.
    Only filters whose added label names start with the prefix are considered.
    UI: checkboxes for each label, editable new patterns, and a button to update selected.
    """
    # Top-level imports provide get_gmail_service, load_json, make_or_pattern, sanitize_to_regex_terms

    error = None
    filters = []
    gmail_label_prefix = (
        request.POST.get("gmail_label_prefix")
        or request.GET.get("gmail_label_prefix")
        or os.environ.get("JOB_HUNT_LABEL_PREFIX")
        or "#job-hunt"
    )
    if request.method == "POST" and request.POST.get("action") == "update":
        # Handle update: only update checked labels
        patterns_path = Path("json/patterns.json")
        label_map_path = Path("json/gmail_label_map.json")
        patterns = load_json(patterns_path, default={"message_labels": {}})
        msg_labels = patterns.setdefault("message_labels", {})
        updated = 0
        for i in range(0, 100):
            if not request.POST.get(f"label_{i}"):
                continue
            if not request.POST.get(f"update_{i}"):
                continue
            request.POST.get(f"label_{i}")
            internal = request.POST.get(f"internal_{i}")
            new_patterns = request.POST.get(f"new_patterns_{i}")
            if not internal or not new_patterns:
                continue
            # Split and clean
            pat_list = [p.strip() for p in new_patterns.splitlines() if p.strip()]
            if pat_list:
                msg_labels[internal] = pat_list
                updated += 1
        with open(patterns_path, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2, ensure_ascii=False)
        messages.success(
            request, f"✅ Updated {updated} label pattern(s) in patterns.json."
        )
        return redirect("gmail_filters_labels_compare")
    elif request.method == "POST" and request.POST.get("action") == "fetch":
        # fall through to fetch logic
        pass
    elif request.method == "GET":
        # fall through to fetch logic
        pass
    try:
        service = get_gmail_service()
        if not service:
            raise RuntimeError(
                "Failed to initialize Gmail service. Check OAuth credentials in json/."
            )
        prefix = gmail_label_prefix.strip()
        labels_resp = service.users().labels().list(userId="me").execute()
        id_to_name = {
            lab.get("id"): lab.get("name") for lab in labels_resp.get("labels", [])
        }
        # name_to_id unused; kept for potential future use
        filt_resp = service.users().settings().filters().list(userId="me").execute()
        filters_raw = filt_resp.get("filter", []) or []
        # Load current patterns and label map
        patterns_path = Path("json/patterns.json")
        label_map_path = Path("json/gmail_label_map.json")
        patterns = load_json(patterns_path, default={"message_labels": {}})
        msg_labels = patterns.setdefault("message_labels", {})
        label_map = load_json(label_map_path, default={})
        # Build filter list for display
        for f in filters_raw:
            criteria = f.get("criteria", {}) or {}
            action = f.get("action", {}) or {}
            add_ids = action.get("addLabelIds", []) or []
            target_label_names = [id_to_name.get(i, "") for i in add_ids]
            matched_names = [
                nm
                for nm in target_label_names
                if isinstance(nm, str) and nm.startswith(prefix)
            ]
            if not matched_names:
                continue
            for lname in matched_names:
                gmail_label = lname
                internal = label_map.get(gmail_label)
                if not internal:
                    # allow direct internal and synonyms
                    direct = gmail_label.strip()
                    base_key = direct.lower().split("/")[-1]
                    synonyms = {
                        # Map Gmail label suffixes to our internal message_labels keys
                        "rejection": "rejection",
                        "reject": "rejection",
                        "rejected": "rejection",
                        "application": "application",
                        "apply": "application",
                        "interview": "interview",
                        "prescreen": "interview",
                        "headhunter": "head_hunter",
                        "head_hunter": "head_hunter",
                        "noise": "noise",
                        "referral": "referral",
                        "offer": "offer",
                        "follow_up": "follow_up",
                        "followup": "follow_up",
                        "response": "response",
                        "ghosted": "ghosted",
                        "other": "other",
                        "ignore": "ignore",
                    }
                    tentative = synonyms.get(base_key, direct)
                    allowed_labels = set(msg_labels.keys()) | {
                        "application",
                        "interview",
                        "rejection",
                        "head_hunter",
                        "noise",
                        "referral",
                        "offer",
                        "follow_up",
                        "response",
                        "ghosted",
                        "other",
                        "ignore",
                    }
                    internal = tentative if tentative in allowed_labels else None
                # Build new patterns from filter
                terms = []
                for key in ("subject", "hasTheWord"):
                    terms += sanitize_to_regex_terms(criteria.get(key, ""))
                pattern = make_or_pattern(terms)
                new_patterns = [pattern] if pattern else []
                old_patterns = msg_labels.get(internal, []) if internal else []
                filters.append(
                    {
                        "label": gmail_label,
                        "internal": internal or "",
                        "old_patterns": old_patterns,
                        "new_patterns": new_patterns,
                        "checked": bool(
                            internal
                            and new_patterns
                            and (set(new_patterns) != set(old_patterns))
                        ),
                    }
                )
    except Exception as e:
        error = f"Failed to fetch Gmail filters: {e}"
    ctx = {
        "filters": filters,
        "error": error,
        "gmail_label_prefix": gmail_label_prefix,
    }
    return render(request, "tracker/gmail_filters_labels_compare.html", ctx)


# --- Delete Company Page ---
@login_required
def delete_company(request, company_id):
    """Delete a company and all related messages/applications, then retrain model."""
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        messages.error(
            request,
            f"❌ Company with ID {company_id} not found. It may have already been deleted.",
        )
        return redirect("label_companies")

    if request.method == "POST":
        company_name = company.name

        # Count related data before deletion (including noise messages)
        total_message_count = Message.objects.filter(company=company).count()
        noise_message_count = Message.objects.filter(
            company=company, ml_label="noise"
        ).count()
        non_noise_message_count = total_message_count - noise_message_count
        application_count = ThreadTracking.objects.filter(company=company).count()

        # Delete all related messages, applications, etc.
        Message.objects.filter(company=company).delete()
        ThreadTracking.objects.filter(company=company).delete()
        # Remove company itself
        company.delete()

        # Show detailed deletion info
        messages.success(request, f"✅ Company '{company_name}' deleted successfully.")
        if noise_message_count > 0:
            messages.info(
                request,
                f"📊 Removed {non_noise_message_count} messages ({noise_message_count} noise) and {application_count} applications.",
            )
        else:
            messages.info(
                request,
                f"📊 Removed {total_message_count} messages and {application_count} applications.",
            )

        # Trigger model retraining in background
        messages.info(request, "🔄 Retraining model to update training data...")
        try:
            result = subprocess.run(
                [python_path, "train_model.py"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0:
                messages.success(
                    request, "✅ Model retrained successfully. Training data updated."
                )
            else:
                messages.warning(
                    request,
                    f"⚠️ Model retraining encountered issues. You may need to retrain manually.",
                )
        except subprocess.TimeoutExpired:
            messages.warning(
                request,
                "⚠️ Model retraining timed out. Please retrain manually from the sidebar.",
            )
        except Exception as e:
            messages.warning(
                request,
                f"⚠️ Could not auto-retrain model: {str(e)}. Please retrain manually.",
            )

        return redirect("label_companies")
    ctx = {"company": company}
    return render(request, "tracker/delete_company.html", ctx)


# --- Label Companies Page ---
@login_required
def label_companies(request):
    """List companies for labeling and provide quick actions (create/select/update)."""
    # Quick Add Company action (before loading companies list)
    if request.method == "POST" and request.POST.get("action") == "quick_add_company":
        company_name = request.POST.get("new_company_name", "").strip()
        if company_name:
            try:
                new_company, created = Company.objects.get_or_create(
                    name=company_name,
                    defaults={
                        "confidence": 1.0,
                        "status": "application",
                        "first_contact": now(),
                        "last_contact": now(),
                    },
                )
                if created:
                    messages.success(
                        request, f"✅ Company '{company_name}' created successfully!"
                    )
                    return redirect(f"/label_companies/?company={new_company.id}")
                else:
                    messages.info(
                        request, f"ℹ️ Company '{company_name}' already exists."
                    )
                    return redirect(f"/label_companies/?company={new_company.id}")
            except Exception as e:
                messages.error(request, f"❌ Failed to create company: {e}")
        else:
            messages.error(request, "❌ Please enter a company name.")
        return redirect("label_companies")

    # Exclude headhunter companies from the dropdown
    companies = Company.objects.exclude(status="headhunter").order_by(Lower("name"))
    # Preserve selected company on POST actions as well
    selected_id = request.GET.get("company") or request.POST.get("company")
    selected_company = None
    latest_label = None
    last_message_ts = None
    days_since_last_message = None
    # Configurable threshold for ghosted hint (default 30). DB AppSetting overrides env.
    from tracker.models import AppSetting

    ghosted_days_threshold = 30
    try:
        db_val = (
            AppSetting.objects.filter(key="GHOSTED_DAYS_THRESHOLD")
            .values_list("value", flat=True)
            .first()
        )
        if db_val is not None and str(db_val).strip() != "":
            ghosted_days_threshold = int(str(db_val).strip())
        else:
            env_val = (
                (os.environ.get("GHOSTED_DAYS_THRESHOLD") or "")
                .strip()
                .replace('"', "")
            )
            if env_val:
                ghosted_days_threshold = int(env_val)
    except Exception:
        pass
    if ghosted_days_threshold < 1 or ghosted_days_threshold > 3650:
        ghosted_days_threshold = 30
    form = None
    message_count = 0
    message_info_list = []
    if selected_id:
        try:
            selected_company = Company.objects.get(id=selected_id)
            # Load career URL from companies.json JobSites
            companies_json_path = Path("json/companies.json")
            career_url = ""
            try:
                if companies_json_path.exists():
                    with open(companies_json_path, "r", encoding="utf-8") as f:
                        companies_json_data = json.load(f)
                        career_url = companies_json_data.get("JobSites", {}).get(
                            selected_company.name, ""
                        )
            except Exception:
                pass
        except Company.DoesNotExist:
            selected_company = None
            messages.warning(
                request,
                f"⚠️ Company with ID {selected_id} not found. It may have been deleted.",
            )
        if selected_company:
            # Get latest label from messages
            latest_msg = (
                Message.objects.filter(company=selected_company, ml_label__isnull=False)
                .order_by("-timestamp")
                .first()
            )
            latest_label = latest_msg.ml_label if latest_msg else None
            # If the latest message is a rejection, ensure company status reflects that
            try:
                if (
                    latest_label == "rejection"
                    and selected_company.status != "rejected"
                ):
                    selected_company.status = "rejected"
                    selected_company.save()
                    messages.info(
                        request,
                        f"ℹ️ Company status set to 'rejected' based on latest message label.",
                    )
            except Exception:
                pass

            # Get message count and (date, subject, label) list (exclude noise messages)
            messages_qs = (
                Message.objects.filter(company=selected_company)
                .exclude(ml_label="noise")
                .order_by("-timestamp")
            )
            message_count = messages_qs.count()
            # Provide (id, timestamp, subject, ml_label) for deep links to label_messages focus
            message_info_list = list(
                messages_qs.values_list("id", "timestamp", "subject", "ml_label")
            )
            # Compute days since last message for ghosted assessment
            if message_count > 0:
                last_message_ts = messages_qs.first().timestamp
                try:
                    days_since_last_message = (now() - last_message_ts).days
                except Exception:
                    days_since_last_message = None
            if request.method == "POST":
                # Quick action: mark as ghosted
                if request.POST.get("action") == "mark_ghosted":
                    # Do not allow ghosted if last message was a rejection
                    if latest_label == "rejection":
                        messages.error(
                            request,
                            "❌ Cannot mark as ghosted: the latest message is a rejection.",
                        )
                    else:
                        try:
                            selected_company.status = "ghosted"
                            selected_company.save()
                            messages.success(
                                request,
                                f"✅ Marked {selected_company.name} as ghosted.",
                            )
                        except Exception as e:
                            messages.error(request, f"Failed to mark ghosted: {e}")
                    # Redirect to avoid form resubmission and preserve selection
                    return redirect(f"/label_companies/?company={selected_company.id}")
                form = CompanyEditForm(request.POST, instance=selected_company)
                if form.is_valid():
                    # Save career URL to companies.json JobSites
                    career_url_input = form.cleaned_data.get("career_url", "").strip()
                    if career_url_input and selected_company.name:
                        try:
                            companies_json_path = Path("json/companies.json")
                            if companies_json_path.exists():
                                with open(
                                    companies_json_path, "r", encoding="utf-8"
                                ) as f:
                                    companies_json_data = json.load(f)

                                if "JobSites" not in companies_json_data:
                                    companies_json_data["JobSites"] = {}

                                companies_json_data["JobSites"][
                                    selected_company.name
                                ] = career_url_input

                                with open(
                                    companies_json_path, "w", encoding="utf-8"
                                ) as f:
                                    json.dump(
                                        companies_json_data,
                                        f,
                                        indent=2,
                                        ensure_ascii=False,
                                    )
                        except Exception as e:
                            print(f"⚠️ Failed to save career URL: {e}")
                    form.save()
                    messages.success(request, "✅ Company details saved.")
                    return redirect(f"/label_companies/?company={selected_company.id}")
                # If invalid, fall through to render the bound form with errors
            else:
                # GET request: initialize form with current data and career URL from companies.json
                form = CompanyEditForm(
                    instance=selected_company, initial={"career_url": career_url}
                )

    ctx = build_sidebar_context()
    ctx.update(
        {
            "company_list": companies,
            "selected_company": selected_company,
            "form": form,
            "latest_label": latest_label,
            "last_message_ts": last_message_ts,
            "days_since_last_message": days_since_last_message,
            "ghosted_days_threshold": ghosted_days_threshold,
            "message_count": message_count,
            "message_info_list": message_info_list,
        }
    )
    return render(request, "tracker/label_companies.html", ctx)


# --- Merge Companies ---
@login_required
def merge_companies(request):
    """Merge multiple companies: reassign all messages/applications to canonical company, delete duplicates."""
    """Merge multiple companies: reassign all messages/applications to canonical company, delete duplicates."""
    if request.method == "POST":
        company_ids = request.POST.getlist("company_ids")
        canonical_id = request.POST.get("canonical_id")

        if not company_ids or len(company_ids) < 2:
            messages.error(request, "⚠️ Please select at least 2 companies to merge.")
            return redirect("label_companies")

        if not canonical_id or canonical_id not in company_ids:
            messages.error(
                request, "⚠️ Please select which company is the canonical (real) name."
            )
            return redirect("label_companies")

        try:
            canonical_company = Company.objects.get(id=canonical_id)
            duplicate_ids = [cid for cid in company_ids if cid != canonical_id]
            duplicates = Company.objects.filter(id__in=duplicate_ids)

            # Reassign all messages
            messages_moved = Message.objects.filter(company__in=duplicates).update(
                company=canonical_company
            )
            # Reassign all applications
            apps_moved = ThreadTracking.objects.filter(company__in=duplicates).update(
                company=canonical_company
            )

            # Update canonical company timestamps if needed
            all_messages = Message.objects.filter(company=canonical_company).order_by(
                "timestamp"
            )
            if all_messages.exists():
                canonical_company.first_contact = all_messages.first().timestamp
                canonical_company.last_contact = all_messages.last().timestamp
                canonical_company.save()

            # Delete duplicate companies
            dup_names = list(duplicates.values_list("name", flat=True))
            duplicates.delete()

            messages.success(
                request,
                f"✅ Merged {len(dup_names)} companies into '{canonical_company.name}'. "
                f"Moved {messages_moved} messages and {apps_moved} applications. Deleted: {', '.join(dup_names)}.",
            )
        except Company.DoesNotExist:
            messages.error(request, "⚠️ Canonical company not found.")
        except Exception as e:
            messages.error(request, f"❌ Merge failed: {e}")

        return redirect("label_companies")

    # GET: show merge form with selected companies
    company_ids = request.GET.getlist("company_ids")
    if not company_ids or len(company_ids) < 2:
        messages.warning(
            request,
            "⚠️ Please select at least 2 companies to merge from the Label Companies page.",
        )
        return redirect("label_companies")

    companies_to_merge = Company.objects.filter(id__in=company_ids).order_by("name")
    ctx = {"companies_to_merge": companies_to_merge}
    return render(request, "tracker/merge_companies.html", ctx)


from datetime import datetime, timedelta

python_path = sys.executable
ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")


def build_sidebar_context():
    """Compute sidebar metrics (companies, applications, weekly trends, upcoming interviews, latest stats)."""
    # Exclude the user's own messages (replies) from counts
    user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()
    # Load headhunter domains from companies.json (if available)
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

    # Count companies only if they have at least one non-headhunter message
    # Build a Q for any headhunter sender (Company context joins via message__sender)
    hh_sender_q = Q()
    for d in headhunter_domains:
        # Match typical email pattern '@domain'
        hh_sender_q |= Q(message__sender__icontains=f"@{d}")

    # Build a Q for Message model context (direct sender field)
    msg_hh_sender_q = Q()
    for d in headhunter_domains:
        msg_hh_sender_q |= Q(sender__icontains=f"@{d}")

    # A non-headhunter message is: not labeled head_hunter AND sender not from any headhunter domain
    non_hh_msg_filter = ~Q(message__ml_label="head_hunter") & ~hh_sender_q

    companies_count = (
        Company.objects.exclude(status="headhunter")
        .annotate(non_hh_msg_count=Count("message", filter=non_hh_msg_filter))
        .filter(non_hh_msg_count__gt=0)
        .count()
    )

    # Authoritative application source: ThreadTracking rows for job applications
    # (created during ingestion for ml_label in ['job_application']).
    tt_app_qs = ThreadTracking.objects.filter(
        ml_label="job_application", company__isnull=False
    )
    # Exclude headhunters by company status and domain (join through messages if needed)
    tt_app_qs = tt_app_qs.exclude(company__status="headhunter")
    applications_count = tt_app_qs.count()

    # Weekly application count: Use Message model directly (more reliable than ThreadTracking)
    # because not all job_application messages have corresponding ThreadTracking rows
    week_cutoff = now() - timedelta(days=7)
    applications_week_qs = Message.objects.filter(
        ml_label__in=["job_application", "application"],
        timestamp__gte=week_cutoff,
        company__isnull=False,
    )
    # Exclude user's own messages
    if user_email:
        applications_week_qs = applications_week_qs.exclude(sender__icontains=user_email)
    # Exclude headhunter companies and domains
    applications_week_qs = applications_week_qs.exclude(company__status="headhunter")
    if headhunter_domains:
        applications_week_qs = applications_week_qs.exclude(msg_hh_sender_q)
    # Count distinct companies
    applications_week = applications_week_qs.values("company_id").distinct().count()

    # Count rejection messages this week (exclude headhunters and user's own replies)
    rejections_qs = Message.objects.filter(
        ml_label__in=["rejected", "rejection"],
        timestamp__gte=now() - timedelta(days=7),
        company__isnull=False,
    )
    if user_email:
        rejections_qs = rejections_qs.exclude(sender__icontains=user_email)
    # Exclude headhunter senders and head_hunter-labeled messages
    if headhunter_domains:
        rejections_qs = rejections_qs.exclude(msg_hh_sender_q)
    rejections_qs = rejections_qs.exclude(ml_label="head_hunter")
    rejections_week = rejections_qs.count()

    # Count interview invitation messages this week
    interviews_qs = Message.objects.filter(
        ml_label="interview_invite",
        timestamp__gte=now() - timedelta(days=7),
        company__isnull=False,
    )
    if user_email:
        interviews_qs = interviews_qs.exclude(sender__icontains=user_email)
    # Exclude headhunter senders/domains for interviews as well
    if headhunter_domains:
        interviews_qs = interviews_qs.exclude(msg_hh_sender_q)
    interviews_week = interviews_qs.count()

    # Upcoming interviews: unify filters with interview list logic (exclude rejected/ghosted)
    upcoming_interviews = (
        ThreadTracking.objects.filter(
            interview_date__gte=now(),
            company__isnull=False,
            interview_completed=False,
        )
        .exclude(status="ghosted")
        .exclude(status="rejected")
        .exclude(rejection_date__isnull=False)
        .select_related("company")
        .order_by("interview_date")[:10]
    )

    latest_stats = IngestionStats.objects.order_by("-date").first()
    return {
        "companies": companies_count,
        "applications": applications_count,
        "applications_count": applications_count,
        "applications_week": applications_week,
        "rejections_week": rejections_week,
        "interviews_week": interviews_week,
        "upcoming_interviews": upcoming_interviews,
        "latest_stats": latest_stats,
    }


# --- Log Viewer Page ---
@login_required
def log_viewer(request):
    """Display and refresh log files from the logs directory."""
    """Display and refresh log files from the logs directory."""
    from django.conf import settings

    logs_dir = Path(settings.BASE_DIR) / "logs"
    log_files = [f.name for f in logs_dir.glob("*.log") if f.is_file()]
    log_files.sort()
    selected_log = request.GET.get("logfile") or (log_files[0] if log_files else None)
    log_content = ""
    if selected_log and (logs_dir / selected_log).exists():
        try:
            with open(
                logs_dir / selected_log, "r", encoding="utf-8", errors="replace"
            ) as f:
                # Read last 100KB to avoid memory issues with huge logs
                log_content = f.read()[-100_000:]
        except Exception as e:
            log_content = f"[Error reading log: {e}]"
    ctx = {
        "log_files": log_files,
        "selected_log": selected_log,
        "log_content": log_content,
    }
    return render(request, "tracker/log_viewer.html", ctx)


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
def manage_aliases(request):
    """Display alias suggestions loaded from json/alias_candidates.json for review."""
    if not ALIAS_EXPORT_PATH.exists():
        ctx = {"suggestions": []}
        return render(request, "tracker/manage_aliases.html", ctx)

    with open(ALIAS_EXPORT_PATH, "r", encoding="utf-8") as f:
        suggestions = json.load(f)

    ctx = {"suggestions": suggestions}
    return render(request, "tracker/manage_aliases.html", ctx)


@csrf_exempt
def approve_bulk_aliases(request):
    """Persist approved alias→company mappings into patterns.json and log approvals."""
    if request.method == "POST":
        aliases = request.POST.getlist("alias")
        suggested = request.POST.getlist("suggested")

        # Load patterns
        if PATTERNS_PATH.exists():
            with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
                patterns = json.load(f)
        else:
            patterns = {"aliases": {}, "ignore": []}

        for alias, suggestion in zip(aliases, suggested):
            patterns["aliases"][alias] = suggestion
            with open(ALIAS_LOG_PATH, "a", encoding="utf-8") as log:
                log.write(f"{alias},{suggestion},{request.POST.get('timestamp')}\n")

        with open(PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2)

        return redirect("manage_aliases")


@csrf_exempt
def reject_alias(request):
    """Add an alias to the ignore list in patterns.json and log the rejection."""
    if request.method == "POST":
        alias = request.POST.get("alias")

        # Load patterns
        if PATTERNS_PATH.exists():
            with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
                patterns = json.load(f)
        else:
            patterns = {"aliases": {}, "ignore": []}

        if alias not in patterns["ignore"]:
            patterns["ignore"].append(alias)

        with open(PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2)

        with open(ALIAS_REJECT_LOG_PATH, "a", encoding="utf-8") as log:
            log.write(f"{alias},{request.POST.get('timestamp')}\n")

        return redirect("manage_aliases")


def edit_application(request, pk):
    """Edit a single application (ThreadTracking) via a simple form."""
    app = get_object_or_404(ThreadTracking, pk=pk)
    if request.method == "POST":
        form = ApplicationEditForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect("flagged_applications")
    else:
        form = ApplicationEditForm(instance=app)
    return render(request, "tracker/edit.html", {"form": form})


def flagged_applications(request):
    """List applications that need attention (unresolved/low-confidence company attribution)."""
    flagged = ThreadTracking.objects.filter(
        models.Q(company="")
        | models.Q(company_source__in=["none", "ml_prediction", "sender_name_match"])
    ).order_by("-first_sent")[:100]

    return render(request, "tracker/flagged.html", {"applications": flagged})


@login_required
def manual_entry(request):
    """Manual entry form for job applications from external sources."""
    if request.method == "POST":
        form = ManualEntryForm(request.POST)
        if form.is_valid():
            # Extract cleaned data
            company_name = form.cleaned_data["company_name"]
            entry_type = form.cleaned_data["entry_type"]
            job_title = form.cleaned_data.get("job_title") or "Manual Entry"
            job_id = form.cleaned_data.get("job_id") or ""
            application_date = form.cleaned_data["application_date"]
            interview_date = form.cleaned_data.get("interview_date")
            notes = form.cleaned_data.get("notes") or ""
            source = form.cleaned_data.get("source") or "manual"

            # Get or create company
            # First try case-insensitive lookup
            existing_company = Company.objects.filter(name__iexact=company_name).first()

            if existing_company:
                company = existing_company
                # Update last contact and status
                company.last_contact = now()
                if entry_type == "rejection":
                    company.status = "rejected"
                elif entry_type == "interview" and company.status != "rejected":
                    company.status = "interview"
                company.save()
            else:
                # Create new company
                company = Company.objects.create(
                    name=company_name,
                    first_contact=now(),
                    last_contact=now(),
                    status=entry_type,
                )

            # Generate unique thread_id for manual entry
            import hashlib

            thread_id_base = f"manual_{company_name}_{job_title}_{application_date}_{now().timestamp()}"
            thread_id = hashlib.md5(thread_id_base.encode()).hexdigest()[:16]

            # Create Application record
            status_map = {
                "application": "application",
                "interview": "interview",
                "rejection": "rejected",
            }

            rejection_date = application_date if entry_type == "rejection" else None
            interview_dt = interview_date if entry_type == "interview" else None

            # Create application record (not used after creation, logged implicitly)
            ThreadTracking.objects.create(
                thread_id=thread_id,
                company=company,
                company_source="manual",
                job_title=job_title,
                job_id=job_id,
                status=status_map[entry_type],
                sent_date=application_date,
                rejection_date=rejection_date,
                interview_date=interview_dt,
                ml_label=entry_type,
                ml_confidence=1.0,  # Manual entries are 100% confident
                reviewed=True,
            )

            # Create Message record for tracking
            msg_id = f"manual_{thread_id}"
            subject = f"{entry_type.title()}: {job_title} at {company_name}"
            body = f"Source: {source}\n\n{notes}" if notes else f"Source: {source}"

            Message.objects.create(
                company=company,
                company_source="manual",
                sender=f"manual@{source}",
                subject=subject,
                body=body,
                body_html=f"<p>{body.replace(chr(10), '<br>')}</p>",
                timestamp=now(),
                msg_id=msg_id,
                thread_id=thread_id,
                ml_label=entry_type,
                confidence=1.0,
                reviewed=True,
            )

            messages.success(
                request,
                f"✅ Successfully added {entry_type} for {company_name} - {job_title}",
            )
            return redirect("manual_entry")
    else:
        form = ManualEntryForm()

    # Show recent manual entries
    recent_entries = (
        ThreadTracking.objects.filter(company_source="manual")
        .select_related("company")
        .order_by("-sent_date")[:20]
    )

    ctx = {
        "form": form,
        "recent_entries": recent_entries,
    }
    ctx.update(build_sidebar_context())
    return render(request, "tracker/manual_entry.html", ctx)


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

    from .models import MessageLabel

    def is_valid_color(color):
        # Accept #RRGGBB, #RGB, or valid CSS color names
        if re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", color):
            return True
        # Accept common color names (basic validation)
        css_colors = {
            "red",
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
            # Applications per day
            apps_q = (
                ThreadTracking.objects.filter(sent_date__gte=app_start_date)
                if app_start_date
                else ThreadTracking.objects.none()
            )
            if hh_companies:
                apps_q = apps_q.exclude(company_id__in=hh_companies)
            if company_filter_id:
                apps_q = apps_q.filter(company_id=company_filter_id)
            apps_by_day = apps_q.values("sent_date").annotate(count=models.Count("id"))
            apps_map = {r["sent_date"]: r["count"] for r in apps_by_day}
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
            from django.db.models.functions import TruncDate

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
        elif ml_label == "interview_invite":
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

    # Only count an "Application Sent" if the thread has at least one job_application/application message
    job_app_exists = Exists(
        Message.objects.filter(
            thread_id=OuterRef("thread_id"),
            ml_label__in=["job_application", "application"],
        )
    )
    # Removed the implicit 7-day default range for company breakdown lists.
    # Provide full historical data; client-side date picker (JS) will filter range.
    application_companies_qs = (
        ThreadTracking.objects.filter(
            sent_date__isnull=False,
            company__isnull=False,
        )
        .annotate(has_job_app=job_app_exists)
        .filter(has_job_app=True)
        .exclude(ml_label="noise")
        .select_related("company")
        .values("company_id", "company__name", "sent_date")
        .order_by("-sent_date")
    )
    if hh_company_list:
        application_companies_qs = application_companies_qs.exclude(
            company_id__in=hh_company_list
        )
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

    # Interviews: Application-based (interview_date)
    interview_companies_qs = (
        ThreadTracking.objects.filter(
            interview_date__isnull=False,
            company__isnull=False,
        )
        .exclude(ml_label="noise")
        .exclude(status="ghosted")
        .exclude(status="rejected")
        .exclude(rejection_date__isnull=False)
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

    interview_companies = [
        {
            "company_id": item["company_id"],
            "company__name": item["company__name"],
            "interview_date": item["interview_date"].strftime("%Y-%m-%d"),
        }
        for item in interview_companies_qs
    ]

    ghosted_companies = [
        {
            "company_id": item["company_id"],
            "company__name": item["company__name"],
            "sent_date": item["sent_date"].strftime("%Y-%m-%d"),
        }
        for item in ghosted_companies_qs
    ]

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
    ctx.update(build_sidebar_context())
    return render(request, "tracker/dashboard.html", ctx)


def extract_body_content(raw_html):
    """Return sanitized HTML body if present, otherwise plain-text extracted from the HTML."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script/style/noscript
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Extract body content if present
    body = soup.body
    return str(body) if body else soup.get_text(separator=" ", strip=True)


def label_applications(request):
    """Simple UI to assign labels to application threads and mark them reviewed."""
    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith("label_") and value:
                app_id = int(key.split("_")[1])
                try:
                    app = ThreadTracking.objects.get(pk=app_id)
                    app.ml_label = value
                    app.reviewed = True
                    app.save()
                except Message.DoesNotExist:
                    continue

        return redirect("label_applications")

    apps = ThreadTracking.objects.filter(reviewed=False).order_by("sent_date")[:50]
    ctx = {"applications": apps}
    return render(request, "tracker/label_applications.html", ctx)


@login_required
def label_messages(request):
    """Bulk message labeling interface with checkboxes"""
    training_output = None

    # Handle POST - Bulk label selected messages
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "update_company_registry":
            # Add or update entries in json/companies.json from quick-add form
            company_name = (request.POST.get("company_name") or "").strip()
            company_domain = (request.POST.get("company_domain") or "").strip()
            ats_domain = (request.POST.get("ats_domain") or "").strip()
            careers_url = (request.POST.get("careers_url") or "").strip()

            if not any([company_name, company_domain, ats_domain, careers_url]):
                messages.warning(request, "⚠️ Please provide at least one field to add/update.")
                return redirect(request.get_full_path())

            cfg_path = Path("json/companies.json")
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    companies_cfg = json.load(f)
            except Exception as e:  # pylint: disable=broad-except
                messages.error(request, f"❌ Failed to read companies.json: {e}")
                return redirect(request.get_full_path())

            added = []
            updated = []

            # Ensure top-level keys exist
            companies_cfg.setdefault("known", [])
            companies_cfg.setdefault("domain_to_company", {})
            companies_cfg.setdefault("ats_domains", [])
            companies_cfg.setdefault("JobSites", {})

            # Add company name to known list
            if company_name:
                if company_name not in companies_cfg["known"]:
                    companies_cfg["known"].append(company_name)
                    added.append(f"known: {company_name}")

            # Map company domain to company name
            if company_domain:
                domain_key = company_domain.lower()
                existing = companies_cfg["domain_to_company"].get(domain_key)
                if not existing:
                    companies_cfg["domain_to_company"][domain_key] = company_name or existing or ""
                    added.append(f"domain_to_company: {domain_key} → {companies_cfg['domain_to_company'][domain_key]}")
                elif company_name and existing != company_name:
                    companies_cfg["domain_to_company"][domain_key] = company_name
                    updated.append(f"domain_to_company: {domain_key} → {company_name}")

            # Add ATS domain
            if ats_domain:
                ats_key = ats_domain.lower()
                if ats_key not in companies_cfg["ats_domains"]:
                    companies_cfg["ats_domains"].append(ats_key)
                    added.append(f"ats_domains: {ats_key}")

            # Add or update careers URL under JobSites
            if careers_url and company_name:
                existing_url = companies_cfg["JobSites"].get(company_name)
                if not existing_url:
                    companies_cfg["JobSites"][company_name] = careers_url
                    added.append(f"JobSites: {company_name}")
                elif existing_url != careers_url:
                    companies_cfg["JobSites"][company_name] = careers_url
                    updated.append(f"JobSites: {company_name}")

            # Persist changes if any
            try:
                if added or updated:
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(companies_cfg, f, ensure_ascii=False, indent=2)
                    if added:
                        messages.success(request, "✅ Added entries: " + "; ".join(added))
                    if updated:
                        messages.info(request, "ℹ️ Updated entries: " + "; ".join(updated))
                else:
                    messages.info(request, "No changes needed; companies.json already up to date.")
            except Exception as e:  # pylint: disable=broad-except
                messages.error(request, f"❌ Failed to write companies.json: {e}")

            return redirect(request.get_full_path())

        if action == "bulk_label":
            selected_ids = request.POST.getlist("selected_messages")
            bulk_label = request.POST.get("bulk_label")

            if selected_ids and bulk_label:
                updated_count = 0
                touched_threads = set()
                for msg_id in selected_ids:
                    try:
                        msg = Message.objects.get(pk=msg_id)
                        msg.ml_label = bulk_label
                        msg.reviewed = True
                        msg.save()
                        if msg.thread_id:
                            touched_threads.add(msg.thread_id)
                        updated_count += 1
                    except Message.DoesNotExist:
                        continue

                # Also update corresponding Application rows by thread_id
                apps_updated = 0
                if touched_threads:
                    apps_updated = ThreadTracking.objects.filter(
                        thread_id__in=list(touched_threads)
                    ).update(ml_label=bulk_label, reviewed=True)

                messages.success(
                    request,
                    f"✅ Labeled {updated_count} messages as '{bulk_label}'"
                    + (
                        f" and updated {apps_updated} application(s)"
                        if apps_updated
                        else ""
                    ),
                )

                # Trigger model retraining in background whenever messages are labeled
                messages.info(request, "🔄 Retraining model to update training data...")
                try:
                    # pylint: disable=consider-using-with
                    subprocess.Popen([python_path, "train_model.py"])
                    messages.success(
                        request, "✅ Model retraining started in background"
                    )
                except Exception as e:
                    messages.warning(
                        request,
                        f"⚠️ Could not start retraining: {e}. Please retrain manually from the sidebar.",
                    )
            else:
                messages.warning(request, "⚠️ Please select messages and a label")

        elif action == "reassign_company":
            selected_ids = request.POST.getlist("selected_messages")
            company_id = request.POST.get("company_id")

            if selected_ids and company_id:
                try:
                    if company_id == "none":
                        company = None
                    else:
                        company = Company.objects.get(pk=int(company_id))

                    updated_count = 0
                    for msg_id in selected_ids:
                        try:
                            msg = Message.objects.get(pk=msg_id)
                            msg.company = company
                            # Explicitly preserve existing label - only update company
                            msg.save(update_fields=["company"])
                            updated_count += 1
                        except Message.DoesNotExist:
                            continue

                    company_name = company.name if company else "None"
                    messages.success(
                        request,
                        f"✅ Reassigned {updated_count} message(s) to company: {company_name}",
                    )
                except Company.DoesNotExist:
                    messages.error(request, "❌ Selected company not found")
                except ValueError:
                    messages.error(request, "❌ Invalid company ID")
            else:
                messages.warning(request, "⚠️ Please select messages and a company")

        elif action == "mark_all_reviewed":
            # Updated behavior: only mark explicitly selected (checked) messages
            selected_ids = request.POST.getlist("selected_messages")

            if selected_ids:
                updated_count = (
                    Message.objects.filter(pk__in=selected_ids).update(reviewed=True)
                )

                messages.success(
                    request,
                    f"✅ Marked {updated_count} selected message(s) as reviewed",
                )

                # Trigger model retraining in background when messages are marked as reviewed
                messages.info(request, "🔄 Retraining model to update training data...")
                try:
                    # pylint: disable=consider-using-with
                    subprocess.Popen([python_path, "train_model.py"])
                    messages.success(
                        request, "✅ Model retraining started in background"
                    )
                except Exception as e:
                    messages.warning(
                        request,
                        f"⚠️ Could not start retraining: {e}. Please retrain manually from the sidebar.",
                    )
            else:
                messages.warning(
                    request,
                    "⚠️ Please select one or more messages to mark as reviewed",
                )

            return redirect(request.get_full_path())

        elif action == "reingest_selected":
            # Re-ingest selected messages from Gmail
            selected_ids = request.POST.getlist("selected_messages")

            if selected_ids:
                try:
                    from parser import ingest_message

                    service = get_gmail_service()
                    success_count = 0
                    error_count = 0

                    for db_id in selected_ids:
                        try:
                            msg = Message.objects.get(pk=db_id)
                            gmail_msg_id = msg.msg_id

                            # Re-ingest from Gmail
                            result = ingest_message(service, gmail_msg_id)
                            if result:
                                success_count += 1
                            else:
                                error_count += 1
                        except Message.DoesNotExist:
                            error_count += 1
                            continue
                        except Exception as e:
                            error_count += 1
                            logger.error(f"Error re-ingesting message {db_id}: {e}")
                            continue

                    if success_count > 0:
                        messages.success(
                            request,
                            f"✅ Re-ingested {success_count} message(s) from Gmail",
                        )
                    if error_count > 0:
                        messages.warning(
                            request, f"⚠️ Failed to re-ingest {error_count} message(s)"
                        )
                except Exception as e:
                    messages.error(request, f"❌ Re-ingestion failed: {e}")
            else:
                messages.warning(request, "⚠️ Please select messages to re-ingest")

            # Redirect to refresh the page with current filters
            return redirect(request.get_full_path())

    # Get pagination parameters
    per_page = int(request.GET.get("per_page", 50))
    page = int(request.GET.get("page", 1))

    # Enhanced filtering
    filter_label = request.GET.get("label", "all")
    filter_confidence = request.GET.get("confidence", "all")  # low, medium, high, all
    filter_company = request.GET.get("company", "all")  # all, missing, resolved
    filter_reviewed = request.GET.get(
        "reviewed", "unreviewed"
    )  # unreviewed, reviewed, all
    search_query = request.GET.get("search", "").strip()  # text search
    hide_noise = request.GET.get("hide_noise", "false").lower() in (
        "true",
        "1",
        "yes",
    )  # checkbox filter
    # Sorting params (default to date desc when not provided)
    sort = (request.GET.get("sort") or "").strip()  # subject, company, confidence, sender_domain, date
    order = (request.GET.get("order") or "").strip()  # asc, desc
    # Focus support
    focus_msg_id = request.GET.get("focus") or request.GET.get("focus_msg_id")
    # Apply default sort only when user didn't specify any sort
    if not sort:
        sort = "date"
        order = "desc"
    # If a sort was provided but order wasn't, default to ascending for consistency
    elif sort and not order:
        order = "asc"

    # Build queryset based on reviewed filter
    if filter_reviewed == "unreviewed":
        qs = Message.objects.filter(reviewed=False)
    elif filter_reviewed == "reviewed":
        qs = Message.objects.filter(reviewed=True)
    else:
        qs = Message.objects.all()

    # Apply label filter
    if filter_label and filter_label != "all":
        # Normalize: "rejection" matches both "rejection" and "rejected"
        if filter_label == "rejection":
            qs = qs.filter(Q(ml_label="rejection") | Q(ml_label="rejected"))
        else:
            qs = qs.filter(ml_label=filter_label)

    # Apply confidence filter
    if filter_confidence == "low":
        qs = qs.filter(Q(confidence__lt=0.5) | Q(confidence__isnull=True))
    elif filter_confidence == "medium":
        qs = qs.filter(confidence__gte=0.5, confidence__lt=0.75)
    elif filter_confidence == "high":
        qs = qs.filter(confidence__gte=0.75)

    # Apply company filter
    if filter_company == "missing":
        qs = qs.filter(company__isnull=True)
    elif filter_company == "resolved":
        qs = qs.filter(company__isnull=False)
    elif (
        filter_company
        and filter_company != "all"
        and filter_company.startswith("company_")
    ):
        # Filter by specific company ID
        try:
            company_id = int(filter_company.replace("company_", ""))
            qs = qs.filter(company_id=company_id)
        except (ValueError, TypeError):
            pass  # Invalid company ID, ignore filter

    # Apply search filter (searches subject, body, and sender)
    if search_query:
        qs = qs.filter(
            Q(subject__icontains=search_query)
            | Q(body__icontains=search_query)
            | Q(sender__icontains=search_query)
        )

    # Apply hide noise filter
    if hide_noise:
        qs = qs.exclude(ml_label="noise")

    # Do not exclude messages with blank or very short bodies; show all for debugging

    # Annotate helper fields for sorting
    qs = qs.select_related("company").annotate(
        company_name=Coalesce(F("company__name"), Value("")),
    )
    # Annotate sender_domain extracted after '@' when present
    at_pos = StrIndex(F("sender"), Value("@"))
    start_pos = ExpressionWrapper(at_pos + Value(1), output_field=IntegerField())
    sender_domain_expr = Case(
        When(sender__contains="@", then=Substr(F("sender"), start_pos)),
        default=F("sender"),
        output_field=CharField(),
    )
    qs = qs.annotate(sender_domain=sender_domain_expr)

    # Sorting
    sort = sort.lower()
    order = order.lower()
    is_desc = order == "desc"

    if sort == "confidence":
        qs = qs.order_by(
            (
                F("confidence").desc(nulls_last=True)
                if is_desc
                else F("confidence").asc(nulls_first=True)
            ),
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "company":
        qs = qs.order_by(
            "-company_name" if is_desc else "company_name",
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "sender_domain":
        qs = qs.order_by(
            "-sender_domain" if is_desc else "sender_domain",
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "subject":
        qs = qs.order_by(
            "-subject" if is_desc else "subject",
            "-timestamp" if is_desc else "timestamp",
        )
    elif sort == "date":
        # Include id as a tiebreaker for deterministic ordering
        qs = qs.order_by(
            ("-timestamp" if is_desc else "timestamp"), ("-id" if is_desc else "id")
        )
    else:
        # Fallback: order by confidence priority similar to previous behavior
        if filter_confidence in ("high", "medium"):
            qs = qs.order_by(F("confidence").desc(nulls_last=True), "-timestamp")
        else:
            qs = qs.order_by(F("confidence").asc(nulls_first=True), "timestamp")

    # If focusing a specific message, compute the page where it appears
    if focus_msg_id:
        try:
            target_id = int(focus_msg_id)
            # Verify target exists in current filtered set
            if qs.filter(id=target_id).exists():
                target = Message.objects.get(pk=target_id)
                if sort == "date":
                    if is_desc:
                        # Count items that would appear before the target
                        before_count = qs.filter(
                            Q(timestamp__gt=target.timestamp)
                            | (Q(timestamp=target.timestamp) & Q(id__gt=target.id))
                        ).count()
                    else:
                        before_count = qs.filter(
                            Q(timestamp__lt=target.timestamp)
                            | (Q(timestamp=target.timestamp) & Q(id__lt=target.id))
                        ).count()
                    page = before_count // per_page + 1
        except Exception:
            pass

    # Pagination
    total_count = qs.count()
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    messages_page = qs[start_idx:end_idx]

    # Extract body snippets for display (plain text only)
    for msg in messages_page:
        if msg.body and msg.body.strip():
            soup = BeautifulSoup(msg.body, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            plain_text = soup.get_text(separator=" ", strip=True)
            plain_text = " ".join(plain_text.split())
            msg.body_snippet = plain_text[:200]
        else:
            msg.body_snippet = "[empty body]"

        if msg.subject and msg.subject.strip():
            msg.display_subject = msg.subject
        else:
            msg.display_subject = "[blank subject]"

        if msg.sender:
            sender_parts = msg.sender.split("@")
            msg.sender_domain = sender_parts[1] if len(sender_parts) > 1 else "unknown"
        else:
            msg.sender_domain = "unknown"

    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_previous = page > 1
    has_next = page < total_pages

    # Get stats
    total_unreviewed = Message.objects.filter(reviewed=False).count()
    total_reviewed = Message.objects.filter(reviewed=True).count()

    # Get distinct labels for filter (all labels, not just unreviewed)
    distinct_labels_raw = (
        Message.objects.all().values_list("ml_label", flat=True).distinct()
    )
    # Normalize: merge "rejected" into "rejection"
    distinct_labels = []
    seen = set()
    for lbl in distinct_labels_raw:
        if lbl == "rejected":
            normalized = "rejection"
        else:
            normalized = lbl
        if normalized and normalized not in seen:
            distinct_labels.append(normalized)
            seen.add(normalized)

    # Available label choices
    label_choices = [
        "interview_invite",
        "job_application",
        "rejection",
        "offer",
        "noise",
        "head_hunter",
        "referral",
        "ghosted",
        "follow_up",
        "response",
        "other",
    ]

    # Get label distribution for prioritization
    label_counts = (
        Message.objects.filter(reviewed=True)
        .values("ml_label")
        .annotate(count=Count("ml_label"))
        .order_by("count")
    )

    # Get all companies for the dropdown (sorted by name)
    # Exclude headhunter companies from dropdown

    all_companies = Company.objects.exclude(status="headhunter").order_by(Lower("name"))

    ctx = {
        "message_list": messages_page,
        "filter_label": filter_label,
        "filter_confidence": filter_confidence,
        "filter_company": filter_company,
        "filter_reviewed": filter_reviewed,
        "search_query": search_query,
        "hide_noise": hide_noise,
        "sort": sort,
        "order": order,
        "distinct_labels": distinct_labels,
        "label_choices": label_choices,
        "label_counts": label_counts,
        "total_unreviewed": total_unreviewed,
        "total_reviewed": total_reviewed,
        "total_count": total_count,
        "per_page": per_page,
        "page": page,
        "total_pages": total_pages,
        "has_previous": has_previous,
        "has_next": has_next,
        "training_output": training_output,
        "filter_reviewed": filter_reviewed,
        "all_companies": all_companies,
        "focus_msg_id": (
            int(focus_msg_id) if str(focus_msg_id or "").isdigit() else None
        ),
    }
    return render(request, "tracker/label_messages.html", ctx)


@login_required
def metrics(request):
    """Display model metrics, training audit, and ingestion stats visualizations."""
    metrics = {}
    training_output = None
    metrics_path = Path("model/model_info.json")
    if metrics_path.exists():
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        except Exception:
            metrics = {}
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
    if "labels" in metrics and isinstance(metrics["labels"], list):
        real_labels = [
            label for label in metrics["labels"] if label.lower() in valid_labels
        ]
        extra_labels = [
            label for label in metrics["labels"] if label.lower() not in valid_labels
        ]
        label_breakdown = {
            "real_count": len(real_labels),
            "extra_count": len(extra_labels),
            "real_labels": real_labels,
            "extra_labels": extra_labels,
        }

    ctx = {
        "metrics": metrics,
        "training_output": training_output,
        "label_breakdown": label_breakdown,
        "chart_labels": chart_labels,
        "chart_inserted": chart_inserted,
        "chart_skipped": chart_skipped,
        "chart_ignored": chart_ignored,
    }
    return render(request, "tracker/metrics.html", ctx)


@csrf_exempt
@login_required
def retrain_model(request):
    """Trigger train_model.py script via subprocess and display its output."""
    training_output = None
    if request.method == "POST":
        try:
            result = subprocess.run(
                [python_path, "train_model.py", "--verbose"],
                capture_output=True,
                text=True,
                check=True,
            )
            training_output = result.stdout
            # Optionally, save output to model/model_audit.json
            with open("model/model_audit.json", "w", encoding="utf-8") as f:
                json.dump({"training_output": training_output}, f)
        except subprocess.CalledProcessError as e:
            training_output = f"Retraining failed:\n{e.stderr}"
    ctx = {
        "metrics": {},
        "training_output": training_output,
    }
    return render(request, "tracker/metrics.html", ctx)


def validate_regex_pattern(pattern):
    """
    Validate regex pattern for security issues.
    Returns (is_valid, error_message)
    """
    if not pattern or not isinstance(pattern, str):
        return False, "Pattern must be a non-empty string"

    # Length limit to prevent DoS
    if len(pattern) > 500:
        return False, "Pattern too long (max 500 characters)"

    # Check for suspicious patterns that could cause ReDoS
    # (Regular Expression Denial of Service)
    redos_patterns = [
        r"\(\?\#",  # Comment groups can be abused
        r"\(\?\=.*\)\+",  # Nested lookaheads with quantifiers
        r"\(\?\!.*\)\+",  # Nested negative lookaheads
        r"(\(.*\)\+){3,}",  # Multiple nested groups with quantifiers
    ]

    for redos in redos_patterns:
        if re.search(redos, pattern):
            return False, f"Pattern contains potentially unsafe construct"

    # Try to compile the regex to ensure it's valid
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex: {str(e)}"

    # Check for extremely complex patterns (complexity check)
    quantifier_count = len(re.findall(r"[*+?{]", pattern))
    if quantifier_count > 20:
        return False, "Pattern too complex (too many quantifiers)"

    return True, None


def sanitize_string(value, max_length=200, allow_regex=False):
    """
    Sanitize user input string for security.
    Returns sanitized string or None if invalid.
    For regex patterns, preserves literal characters (no HTML escaping).
    """
    if not value or not isinstance(value, str):
        return None

    # Remove leading/trailing whitespace
    value = value.strip()

    if not value:
        return None

    # Length check
    if len(value) > max_length:
        return None

    # Block obvious code injection attempts (check before any escaping)
    dangerous_chars = [
        "<script",
        "javascript:",
        "onerror=",
        "onload=",
        "<?php",
        "<%",
        "__import__",
        "eval(",
        "exec(",
    ]
    value_lower = value.lower()
    for danger in dangerous_chars:
        if danger in value_lower:
            return None

    # Block path traversal
    if "../" in value or "..\\" in value or "%2e%2e" in value.lower():
        return None

    # Block null bytes
    if "\x00" in value:
        return None

    # For regex patterns, validate but DON'T html-escape (preserves literal chars)
    if allow_regex:
        is_valid, _error = validate_regex_pattern(value)
        if not is_valid:
            return None
        # Return as-is for JSON storage (template will handle display escaping)
        return value

    # For non-regex strings, HTML escape to prevent XSS
    value = html.escape(value)

    return value


def validate_domain(domain):
    """
    Validate domain name format.
    Returns (is_valid, sanitized_domain)
    """
    if not domain or not isinstance(domain, str):
        return False, None

    domain = domain.strip().lower()

    # Length check
    if len(domain) > 253:
        return False, None

    # Basic domain format check
    # Allow letters, numbers, dots, hyphens
    if not re.match(
        r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
        domain,
    ):
        return False, None

    # Must have at least one dot (TLD)
    if "." not in domain:
        return False, None

    # HTML escape for safety
    domain = html.escape(domain)

    return True, domain


@login_required
def json_file_viewer(request):
    """View and edit JSON configuration files (patterns.json, companies.json)"""

    patterns_path = Path("json/patterns.json")
    companies_path = Path("json/companies.json")

    success_message = None
    error_message = None
    validation_errors = []

    # Handle POST - Save changes to JSON files
    if request.method == "POST":
        action = request.POST.get("action")
        request.POST.get("file_type")

        try:
            if action == "save_patterns":
                # Update patterns.json with security validation
                patterns_data = {}

                # Save message_labels patterns with validation
                for label in [
                    "interview",
                    "application",
                    "rejection",
                    "offer",
                    "noise",
                    "referral",
                    "head_hunter",
                    "follow_up",
                    "response",
                    "ghosted",
                    "other",
                ]:
                    patterns_raw = (
                        request.POST.get(f"pattern_{label}", "").strip().split("\n")
                    )
                    patterns_list = []

                    for pattern in patterns_raw:
                        if not pattern.strip():
                            continue

                        # Validate and sanitize regex pattern
                        sanitized = sanitize_string(
                            pattern, max_length=500, allow_regex=True
                        )
                        if sanitized:
                            patterns_list.append(sanitized)
                        else:
                            validation_errors.append(
                                f"Invalid pattern in '{label}': {pattern[:50]}..."
                            )

                    if patterns_list:
                        if "message_labels" not in patterns_data:
                            patterns_data["message_labels"] = {}
                        patterns_data["message_labels"][label] = patterns_list

                # Save invalid_company_prefixes with validation
                invalid_prefixes_raw = (
                    request.POST.get("invalid_company_prefixes", "").strip().split("\n")
                )
                invalid_prefixes = []

                for prefix in invalid_prefixes_raw:
                    if not prefix.strip():
                        continue

                    # Allow regex (including \\s) in invalid_company_prefixes
                    sanitized = sanitize_string(
                        prefix, max_length=100, allow_regex=True
                    )
                    if sanitized:
                        # Validate regex (warn but allow fallback)
                        try:
                            re.compile(sanitized)
                            invalid_prefixes.append(sanitized)
                        except re.error:
                            validation_errors.append(
                                f"Invalid regex in company prefix: {prefix[:50]}..."
                            )
                    else:
                        validation_errors.append(
                            f"Invalid company prefix: {prefix[:50]}..."
                        )

                if invalid_prefixes:
                    patterns_data["invalid_company_prefixes"] = invalid_prefixes

                # Save old-style patterns for backward compatibility
                for key in [
                    "application",
                    "rejection",
                    "interview",
                    "ignore",
                    "response",
                    "follow_up",
                ]:
                    old_patterns_raw = (
                        request.POST.get(f"old_{key}", "").strip().split("\n")
                    )
                    old_patterns = []

                    for pattern in old_patterns_raw:
                        if not pattern.strip():
                            continue

                        sanitized = sanitize_string(
                            pattern, max_length=500, allow_regex=False
                        )
                        if sanitized:
                            old_patterns.append(sanitized)

                    if old_patterns:
                        patterns_data[key] = old_patterns

                # Only write if no validation errors
                if validation_errors:
                    error_message = f"⚠️ Validation errors: {len(validation_errors)} patterns rejected for security reasons"
                else:
                    # Backup original file before overwriting
                    if patterns_path.exists():
                        backup_path = Path("json/patterns.json.backup")
                        import shutil

                        shutil.copy2(patterns_path, backup_path)

                    # Write to file with restrictive permissions
                    with open(patterns_path, "w", encoding="utf-8") as f:
                        json.dump(patterns_data, f, indent=2)

                    success_message = "✅ Patterns saved successfully! (Backup created)"

            elif action == "save_companies":
                # Update companies.json with security validation
                companies_data = {}

                # Save known companies with validation
                known_raw = request.POST.get("known_companies", "").strip().split("\n")
                known_list = []

                for company in known_raw:
                    if not company.strip():
                        continue

                    # Validate company name
                    sanitized = sanitize_string(
                        company, max_length=200, allow_regex=False
                    )
                    if sanitized:
                        known_list.append(sanitized)
                    else:
                        validation_errors.append(
                            f"Invalid company name: {company[:50]}..."
                        )

                if known_list:
                    companies_data["known"] = sorted(known_list)

                # Save domain mappings with validation
                domain_mappings = {}
                domains_raw = (
                    request.POST.get("domain_mappings", "").strip().split("\n")
                )

                for line in domains_raw:
                    if not line.strip():
                        continue

                    if ":" in line or "=" in line:
                        separator = ":" if ":" in line else "="
                        parts = line.split(separator, 1)

                        if len(parts) == 2:
                            domain = parts[0].strip()
                            company = parts[1].strip()

                            # Validate domain format
                            is_valid, sanitized_domain = validate_domain(domain)
                            if not is_valid:
                                validation_errors.append(
                                    f"Invalid domain format: {domain}"
                                )
                                continue

                            # Validate company name
                            sanitized_company = sanitize_string(
                                company, max_length=200, allow_regex=False
                            )
                            if not sanitized_company:
                                validation_errors.append(
                                    f"Invalid company name for domain {domain}"
                                )
                                continue

                            domain_mappings[sanitized_domain] = sanitized_company

                if domain_mappings:
                    companies_data["domain_to_company"] = domain_mappings

                # Save ATS domains with validation
                ats_raw = request.POST.get("ats_domains", "").strip().split("\n")
                ats_list = []

                for domain in ats_raw:
                    if not domain.strip():
                        continue

                    # Validate domain format
                    is_valid, sanitized_domain = validate_domain(domain)
                    if is_valid:
                        ats_list.append(sanitized_domain)
                    else:
                        validation_errors.append(f"Invalid ATS domain: {domain}")

                if ats_list:
                    companies_data["ats_domains"] = sorted(ats_list)

                # Save headhunter domains with validation
                headhunter_raw = (
                    request.POST.get("headhunter_domains", "").strip().split("\n")
                )
                headhunter_list = []

                for domain in headhunter_raw:
                    if not domain.strip():
                        continue

                    # Validate domain format
                    is_valid, sanitized_domain = validate_domain(domain)
                    if is_valid:
                        headhunter_list.append(sanitized_domain)
                    else:
                        validation_errors.append(f"Invalid headhunter domain: {domain}")

                if headhunter_list:
                    companies_data["headhunter_domains"] = sorted(headhunter_list)

                # Save JobSites (Company → Career URL mapping) with validation
                job_sites = {}
                job_sites_raw = request.POST.get("job_sites", "").strip().split("\n")

                for line in job_sites_raw:
                    if not line.strip():
                        continue

                    if ":" in line:
                        parts = line.split(":", 1)

                        if len(parts) == 2:
                            company = parts[0].strip()
                            url = parts[1].strip()

                            # Validate company name
                            sanitized_company = sanitize_string(
                                company, max_length=200, allow_regex=False
                            )

                            # Validate URL (must be http/https)
                            if sanitized_company and url:
                                if url.startswith(("http://", "https://")):
                                    # Basic URL validation - check for common injection patterns
                                    if not any(
                                        char in url
                                        for char in ["<", ">", '"', "'", "javascript:"]
                                    ):
                                        job_sites[sanitized_company] = url
                                    else:
                                        validation_errors.append(
                                            f"Invalid URL for {company}: contains unsafe characters"
                                        )
                                else:
                                    validation_errors.append(
                                        f"Invalid URL for {company}: must start with http:// or https://"
                                    )
                            else:
                                validation_errors.append(
                                    f"Invalid job site entry: {company} → {url}"
                                )

                if job_sites:
                    companies_data["JobSites"] = job_sites

                # Save aliases with validation
                aliases = {}
                aliases_raw = request.POST.get("aliases", "").strip().split("\n")

                for line in aliases_raw:
                    if not line.strip():
                        continue

                    if ":" in line or "=" in line:
                        separator = ":" if ":" in line else "="
                        parts = line.split(separator, 1)

                        if len(parts) == 2:
                            alias = parts[0].strip()
                            canonical = parts[1].strip()

                            # Validate both alias and canonical names
                            sanitized_alias = sanitize_string(
                                alias, max_length=200, allow_regex=False
                            )
                            sanitized_canonical = sanitize_string(
                                canonical, max_length=200, allow_regex=False
                            )

                            if sanitized_alias and sanitized_canonical:
                                aliases[sanitized_alias] = sanitized_canonical
                            else:
                                validation_errors.append(
                                    f"Invalid alias: {alias} → {canonical}"
                                )

                if aliases:
                    companies_data["aliases"] = aliases

                # Check for reasonable data size (DoS prevention)
                total_entries = (
                    len(known_list)
                    + len(domain_mappings)
                    + len(ats_list)
                    + len(headhunter_list)
                    + len(job_sites)
                    + len(aliases)
                )

                if total_entries > 10000:
                    error_message = "❌ Too many entries (max 10,000 total). Possible DoS attempt blocked."
                elif validation_errors:
                    error_message = f"⚠️ Validation errors: {len(validation_errors)} entries rejected for security reasons"
                else:
                    # Backup original file before overwriting
                    if companies_path.exists():
                        backup_path = Path("json/companies.json.backup")
                        import shutil

                        shutil.copy2(companies_path, backup_path)

                    # Write to file
                    with open(companies_path, "w", encoding="utf-8") as f:
                        json.dump(companies_data, f, indent=2)

                    success_message = "✅ Companies configuration saved successfully! (Backup created)"

        except Exception as e:
            error_message = f"❌ Error saving file: {str(e)}"

    # Load current JSON data
    patterns_data = {}
    companies_data = {}

    try:
        if patterns_path.exists():
            with open(patterns_path, "r", encoding="utf-8") as f:
                patterns_data = json.load(f)
    except Exception as e:
        error_message = f"⚠️ Error loading patterns.json: {str(e)}"

    try:
        if companies_path.exists():
            with open(companies_path, "r", encoding="utf-8") as f:
                companies_data = json.load(f)
    except Exception as e:
        error_message = f"⚠️ Error loading companies.json: {str(e)}"

    ctx = {
        "patterns_data": patterns_data,
        "companies_data": companies_data,
        "success_message": success_message,
        "error_message": error_message,
        "validation_errors": validation_errors,
    }
    return render(request, "tracker/json_file_viewer.html", ctx)


# --- Re-ingest Gmail Admin ---
@login_required
def reingest_admin(request):
    """Run the ingest_gmail command with options and show output."""
    base_dir = Path(__file__).resolve().parents[1]
    day_choices = [
        ("ALL", "ALL"),
        (1, "1 day"),
        (7, "7 days"),
        (14, "14 days"),
        (30, "30 days"),
    ]
    default_days = 7

    ctx = {
        "result": None,
        "error": None,
        "day_choices": day_choices,
        "default_days": default_days,
    }
    # Include reporting default start date info for the template
    env_start_date = os.environ.get("REPORTING_DEFAULT_START_DATE")
    ctx["reporting_default_start_date"] = env_start_date or ""

    if request.method == "POST":
        days_back = request.POST.get("days_back", str(default_days))
        force = request.POST.get("force") == "on"
        reparse_all = request.POST.get("reparse_all") == "on"

        cmd = [
            sys.executable,
            "manage.py",
            "ingest_gmail",
            "--metrics-before",
            "--metrics-after",
        ]
        if days_back and days_back != "ALL":
            cmd += ["--days-back", str(days_back)]
        if force:
            cmd.append("--force")
        if reparse_all:
            cmd.append("--reparse-all")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(base_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = result.stdout or ""
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            ctx["result"] = output
        except Exception as e:
            ctx["error"] = f"Failed to run ingestion: {e}"

    return render(request, "tracker/reingest_admin.html", ctx)


@login_required
def reingest_stream(request):
    """Stream output from ingest_gmail command for live updates in the UI."""
    base_dir = Path(__file__).resolve().parents[1]
    days_back = request.GET.get("days_back")
    force = request.GET.get("force") == "true"
    reparse_all = request.GET.get("reparse_all") == "true"

    cmd = [
        sys.executable,
        "manage.py",
        "ingest_gmail",
        "--metrics-before",
        "--metrics-after",
        "-u",  # unbuffered
    ]
    if days_back and days_back != "ALL":
        cmd += ["--days-back", str(days_back)]
    if force:
        cmd.append("--force")
    if reparse_all:
        cmd.append("--reparse-all")

    def generate():
        yield f"Running: {' '.join(cmd)}\n\n"
        try:
            with subprocess.Popen(
                cmd,
                cwd=str(base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
            ) as proc:
                for line in proc.stdout:
                    yield line
                ret = proc.wait()
                yield f"\n[exit code] {ret}\n"
        except Exception as e:
            yield f"[error] {e}\n"

    return StreamingHttpResponse(generate(), content_type="text/plain; charset=utf-8")


def _parse_pasted_gmail_spec(text: str):
    """Yield dicts like parse_filters() from pasted Gmail spec blocks.

    Recognizes case-insensitive markers:
      - label:
      - Haswords:
      - DoesNotHave:

    Haswords/DoesNotHave may include quoted phrases and | separators; we pass the
    captured strings to sanitize_to_regex_terms downstream.
    """
    current_label = None
    has_buf: list[str] = []
    not_buf: list[str] = []
    lines = text.splitlines()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m_label = re.match(r"(?i)^label\s*:\s*(.+)$", line)
        if m_label:
            # flush previous
            if current_label:
                yield {
                    "label": current_label,
                    "subject": "",
                    "hasTheWord": " | ".join(has_buf).strip(),
                    "doesNotHaveTheWord": " | ".join(not_buf).strip(),
                }
            current_label = m_label.group(1).strip()
            has_buf, not_buf = [], []
            continue
        if re.match(r"(?i)^haswords\s*:\s*", line):
            parts = line.split(":", 1)
            if len(parts) == 2:
                has_buf.append(parts[1].strip())
            continue
        if re.match(r"(?i)^doesnothave\s*:\s*", line):
            parts = line.split(":", 1)
            if len(parts) == 2:
                not_buf.append(parts[1].strip())
            continue
        # Free text lines after a section: treat as additional Haswords
        if current_label:
            has_buf.append(line)
    if current_label:
        yield {
            "label": current_label,
            "subject": "",
            "hasTheWord": " | ".join(has_buf).strip(),
            "doesNotHaveTheWord": " | ".join(not_buf).strip(),
        }


# --- Configure Settings ---
@login_required
def configure_settings(request):
    """Configure app settings and optionally fetch/apply Gmail filter rules into patterns.json."""
    from tracker.models import AppSetting

    # Known settings and validators
    def clamp_int(val, lo, hi, default):
        try:
            n = int(str(val).strip())
            if n < lo or n > hi:
                return default
            return n
        except Exception:
            return default

    settings_spec = {
        "GHOSTED_DAYS_THRESHOLD": {
            "label": "Ghosted Days Threshold",
            "help": "Days since last message to show 'Consider ghosted' hint.",
            "type": "int",
            "default": 30,
            "min": 1,
            "max": 3650,
        },
    }

    # Load current values from DB (or defaults)
    current = {}
    for key, spec in settings_spec.items():
        db_val = (
            AppSetting.objects.filter(key=key).values_list("value", flat=True).first()
        )
        if db_val is None or str(db_val).strip() == "":
            current[key] = spec["default"]
        else:
            if spec["type"] == "int":
                current[key] = clamp_int(
                    db_val, spec["min"], spec["max"], spec["default"]
                )
            else:
                current[key] = db_val

    preview = None
    if request.method == "POST":
        action = request.POST.get("action") or "save"
        if action == "save":
            # Save posted values
            for key, spec in settings_spec.items():
                raw = request.POST.get(key)
                if spec["type"] == "int":
                    val = clamp_int(raw, spec["min"], spec["max"], spec["default"])
                else:
                    val = (raw or "").strip()
                AppSetting.objects.update_or_create(
                    key=key, defaults={"value": str(val)}
                )
            messages.success(request, "✅ Settings updated.")
            return redirect("configure_settings")
        elif action in ("gmail_filters_preview", "gmail_filters_apply"):
            # Fetch filters via Gmail API and build preview/apply into patterns.json
            try:
                service = get_gmail_service()
                if not service:
                    raise RuntimeError(
                        "Failed to initialize Gmail service. Check OAuth credentials in json/."
                    )
                # Label prefix from env (or default)
                prefix = (
                    request.POST.get("gmail_label_prefix")
                    or os.environ.get("JOB_HUNT_LABEL_PREFIX")
                    or "#job-hunt"
                ).strip()
                # Build label maps
                labels_resp = service.users().labels().list(userId="me").execute()
                id_to_name = {
                    lab.get("id"): lab.get("name")
                    for lab in labels_resp.get("labels", [])
                }
                # name_to_id unused; kept for potential future Gmail API logic
                # Fetch all filters
                filt_resp = (
                    service.users().settings().filters().list(userId="me").execute()
                )
                filters = filt_resp.get("filter", []) or []

                # Convert to entries compatible with existing import logic
                entries = []
                for f in filters:
                    criteria = f.get("criteria", {}) or {}
                    action = f.get("action", {}) or {}
                    add_ids = action.get("addLabelIds", []) or []
                    target_label_names = [id_to_name.get(i, "") for i in add_ids]
                    # Only include filters where at least one added label starts with prefix
                    matched_names = [
                        nm
                        for nm in target_label_names
                        if isinstance(nm, str) and nm.startswith(prefix)
                    ]
                    if not matched_names:
                        continue
                    # For each matched label, produce an entry
                    for lname in matched_names:
                        entries.append(
                            {
                                "label": lname,
                                "subject": criteria.get("subject", ""),
                                "hasTheWord": " | ".join(
                                    [
                                        criteria.get("query", ""),
                                        criteria.get("from", ""),
                                        criteria.get("to", ""),
                                        # keep subject also in hasTheWord for broader match
                                        criteria.get("subject", ""),
                                    ]
                                ).strip(" |"),
                                "doesNotHaveTheWord": criteria.get("negatedQuery", ""),
                            }
                        )

                # Load current patterns and label map
                patterns_path = Path("json/patterns.json")
                label_map_path = Path("json/gmail_label_map.json")
                patterns = load_json(patterns_path, default={"message_labels": {}})
                msg_labels = patterns.setdefault("message_labels", {})
                msg_excludes = patterns.setdefault("message_label_excludes", {})
                label_map = load_json(label_map_path, default={})

                additions = {}
                exclude_additions = {}
                unmatched = set()
                for props in entries:
                    gmail_label = props.get("label")
                    if not gmail_label:
                        continue
                    internal = label_map.get(gmail_label)
                    if not internal:
                        # allow direct internal and synonyms
                        direct = gmail_label.strip()
                        synonyms = {
                            "rejection": "rejected",
                            "reject": "rejected",
                            "application": "job_application",
                            "apply": "job_application",
                            "interview": "interview_invite",
                            "prescreen": "interview_invite",
                            "headhunter": "head_hunter",
                        }
                        tentative = synonyms.get(direct.lower().split("/")[-1], direct)
                        internal = (
                            tentative
                            if tentative in msg_labels
                            or tentative
                            in (
                                "job_application",
                                "interview_invite",
                                "rejected",
                                "head_hunter",
                                "noise",
                            )
                            else None
                        )
                    if not internal:
                        unmatched.add(gmail_label)
                        continue
                    terms = []
                    for key in ("subject", "hasTheWord"):
                        terms += sanitize_to_regex_terms(props.get(key, ""))
                    pattern = make_or_pattern(terms)
                    if pattern:
                        additions.setdefault(internal, set()).add(pattern)
                    ex_terms = sanitize_to_regex_terms(
                        props.get("doesNotHaveTheWord", "")
                    )
                    ex_pat = make_or_pattern(ex_terms)
                    if ex_pat:
                        exclude_additions.setdefault(internal, set()).add(ex_pat)

                # Compute preview
                preview = {
                    "add": {},
                    "exclude": {},
                    "unmatched": sorted(unmatched),
                    "prefix": prefix,
                }
                for label, new in additions.items():
                    before = set(msg_labels.get(label, []))
                    to_add = sorted(set(new) - before)
                    if to_add:
                        preview["add"][label] = to_add
                for label, new in exclude_additions.items():
                    before = set(msg_excludes.get(label, []))
                    to_add = sorted(set(new) - before)
                    if to_add:
                        preview["exclude"][label] = to_add

                if action == "gmail_filters_preview":
                    # fall-through to render with preview
                    pass
                else:
                    # Apply and save
                    for label, new in preview["add"].items():
                        msg_labels[label] = sorted(
                            set(msg_labels.get(label, [])) | set(new)
                        )
                    for label, new in preview["exclude"].items():
                        msg_excludes[label] = sorted(
                            set(msg_excludes.get(label, [])) | set(new)
                        )
                    with open(patterns_path, "w", encoding="utf-8") as f:
                        json.dump(patterns, f, indent=2, ensure_ascii=False)
                    messages.success(
                        request,
                        f"✅ Updated patterns from Gmail API filters (prefix {prefix}).",
                    )
                    return redirect("configure_settings")
            except Exception as e:
                messages.error(request, f"⚠️ Failed to fetch/apply Gmail filters: {e}")

    ctx = {
        "settings_spec": settings_spec,
        "current": current,
        "gmail_filters_preview": json.dumps(preview, indent=2) if preview else None,
    }
    return render(request, "tracker/configure_settings.html", ctx)
