"""Debugging views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

import json
import os
import re
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect
from bs4 import BeautifulSoup

from parser import (
    extract_metadata,
    parse_raw_message,
    predict_with_fallback,
    predict_subject_type,
    parse_subject,
    normalize_company_name,
)
from scripts.import_gmail_filters import (
    load_json,
    make_or_pattern,
    sanitize_to_regex_terms,
)
from gmail_auth import get_gmail_service
from tracker.forms import UploadEmlForm
from scripts.ingest_eml import ingest_eml_bytes


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
    extracted_company = ""
    company_confidence = 0
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
                sender = ""
                sender_domain = ""
                try:
                    if isinstance(msg_obj, str):
                        meta = parse_raw_message(msg_obj)
                    else:
                        # If JSON provided, we don't have Gmail service here; fallback to EML path
                        meta = parse_raw_message(raw_text)
                    subject = meta.get("subject", "")
                    body = meta.get("body", "")
                    sender = meta.get("sender", "")
                    sender_domain = meta.get("sender_domain", "")
                except Exception:
                    # naive fallback: split headers/body for EML-like content
                    parts = raw_text.split("\n\n", 1)
                    if parts:
                        headers = parts[0]
                        body = parts[1] if len(parts) > 1 else raw_text
                        for line in headers.splitlines():
                            if line.lower().startswith("subject:"):
                                subject = line.split(":", 1)[1].strip()
                            elif line.lower().startswith("from:"):
                                sender = line.split(":", 1)[1].strip()
                                # Extract domain from sender
                                match = re.search(r"@([A-Za-z0-9.-]+)$", sender)
                                if match:
                                    sender_domain = match.group(1).lower()
                message_text = body or subject

                # Use the same classification pipeline as ingest_message
                from parser import predict_with_fallback, predict_subject_type

                # Run the full classification pipeline (ML + rules)
                result = predict_with_fallback(
                    predict_subject_type, subject, body, sender=sender
                )

                matched_label = result.get("label", "noise")
                ml_label = result.get("ml_label") or result.get("label")
                matched_confidence = result.get("confidence", 0.0)
                fallback_type = result.get("fallback", "unknown")

                # Now find which patterns matched for highlighting
                patterns_path = Path("json/patterns.json")
                patterns = load_json(patterns_path, default={"message_labels": {}})
                msg_labels = patterns.get("message_labels", {})

                highlights_set = set()
                matched_labels_set = set()

                if matched_label:
                    matched_labels_set.add(matched_label)
                    # Map internal labels back to pattern.json keys
                    label_map_reverse = {
                        "interview_invite": "interview",
                        "job_application": "application",
                    }
                    pattern_key = label_map_reverse.get(matched_label, matched_label)

                    # Find which patterns matched for this label
                    rules = msg_labels.get(pattern_key, [])
                    for rule in rules:
                        if rule == "None":
                            continue
                        try:
                            pattern = re.compile(rule, re.IGNORECASE)
                            match = pattern.search(message_text)
                            if match:
                                matched_patterns.append(f"{matched_label}: {rule}")
                                matched_text = match.group(0)
                                highlights_set.add(matched_text)

                                # Extract OR alternatives for highlighting
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
                        except re.error:
                            continue

                highlights = sorted(highlights_set, key=lambda s: s.lower())
                matched_labels = sorted(matched_labels_set)
                no_matches = not matched_label

                # Extract company name using parse_subject with sender info
                try:
                    parsed = parse_subject(
                        subject, body, sender=sender, sender_domain=sender_domain
                    )
                    extracted_company = parsed.get("company", "")
                    company_confidence = parsed.get("confidence", 0)
                    if extracted_company:
                        extracted_company = normalize_company_name(extracted_company)
                except Exception:
                    # Company extraction failed - continue without it
                    extracted_company = ""
                    company_confidence = 0

                # Apply the same override logic as ingest_message
                override_note = None

                # 1. Check if ML originally predicted head_hunter (internal recruiter override)
                if ml_label == "head_hunter" and sender_domain:
                    from parser import _map_company_by_domain, HEADHUNTER_DOMAINS

                    if sender_domain not in HEADHUNTER_DOMAINS:
                        mapped_company = _map_company_by_domain(sender_domain)
                        if mapped_company:
                            # Check if we should preserve meaningful labels or override to 'other'
                            if matched_label == "job_application":
                                # Check for ATS markers to validate real application
                                body_lower = (body or "").lower()
                                ats_markers = [
                                    "workday",
                                    "myworkday",
                                    "taleo",
                                    "icims",
                                    "indeed",
                                    "list-unsubscribe",
                                    "one-click",
                                ]
                                has_ats_marker = any(
                                    marker in body_lower for marker in ats_markers
                                )
                                if not has_ats_marker:
                                    override_note = f"Override: Internal recruiter from {mapped_company} - no ATS markers, changed to 'other'"
                                    matched_label = "other"
                                    if "other" not in matched_labels_set:
                                        matched_labels.append("other")
                            elif matched_label not in (
                                "interview_invite",
                                "rejection",
                                "offer",
                            ):
                                override_note = f"Override: Internal recruiter from {mapped_company} - changed to 'other' (ML predicted head_hunter)"
                                matched_label = "other"
                                if "other" not in matched_labels_set:
                                    matched_labels.append("other")

                # 2. Check if sender domain is in personal domains list
                if sender_domain:
                    from parser import PERSONAL_DOMAINS

                    if sender_domain.lower() in PERSONAL_DOMAINS:
                        override_note = f"Override: Personal domain ({sender_domain}) - changed to 'noise'"
                        matched_label = "noise"
                        matched_labels = ["noise"]

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
                    "extracted_company": extracted_company,
                    "company_confidence": company_confidence,
                    "override_note": override_note,
                }
            except Exception as e:
                error = f"Failed to parse message: {e}"
    override_note = result.get("override_note") if result else None
    ctx = {
        "result": result,
        "error": error,
        "message_text": message_text,
        "highlights": highlights,
        "matched_label": matched_label,
        "matched_labels": matched_labels,
        "matched_patterns": matched_patterns,
        "no_matches": no_matches,
        "extracted_company": extracted_company,
        "company_confidence": company_confidence,
        "override_note": override_note,
    }
    return render(request, "tracker/label_rule_debugger.html", ctx)


@staff_member_required
def upload_eml(request):
    """Admin/dashboard upload endpoint to ingest a local .eml file via UI."""
    result = None
    error = None
    if request.method == "POST":
        form = UploadEmlForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = request.FILES["eml_file"]
            raw = uploaded.read()
            thread_override = form.cleaned_data.get("thread_id") or None
            no_tt = form.cleaned_data.get("no_tt")
            # Call ingest helper with apply=True
            resp = ingest_eml_bytes(
                raw,
                apply=True,
                create_tt=(not no_tt),
                thread_id_override=thread_override,
            )
            if resp.get("success"):
                result = resp
            else:
                error = resp.get("message")
        else:
            error = "Invalid form submission"
    else:
        form = UploadEmlForm()

    return render(
        request,
        "tracker/upload_eml.html",
        {"form": form, "result": result, "error": error},
    )


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


__all__ = ["label_rule_debugger", "upload_eml", "gmail_filters_labels_compare"]
