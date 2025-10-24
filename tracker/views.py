# --- Label Rule Debugger ---
from pathlib import Path
import json
import re
from scripts.import_gmail_filters import load_json, sanitize_to_regex_terms
from parser import extract_metadata
from django.db.models.functions import Coalesce, Substr, StrIndex
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import (
    F,
    Q,
    Count,
    Case,
    When,
    Value,
    IntegerField,
    CharField,
    ExpressionWrapper,
)
from django.http import StreamingHttpResponse, HttpResponse


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
                # Extract metadata with fallback
                subject = ""
                body = ""
                try:
                    meta = extract_metadata(msg_obj)
                    # meta may be dict-like per project convention
                    subject = (
                        meta.get("subject") if isinstance(meta, dict) else ""
                    ) or subject
                    body = (meta.get("body") if isinstance(meta, dict) else "") or body
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
                # Find which label and pattern(s) match without duplicates
                # Uses STANDARD REGEX (Python re module) with case-insensitive matching
                seen_rules = set()  # (label, rule)
                matched_labels_set = set()
                highlights_set = set()
                for label, rules in msg_labels.items():
                    for rule in rules:
                        if rule == "None":
                            continue

                        # Use the rule as a standard regex pattern
                        try:
                            # Compile regex with case-insensitive flag
                            pattern = re.compile(rule, re.IGNORECASE)
                            match = pattern.search(message_text)

                            if match:
                                if (label, rule) not in seen_rules:
                                    matched_patterns.append(f"{label}: {rule}")
                                    matched_label = label
                                    matched_labels_set.add(label)
                                    seen_rules.add((label, rule))

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
    # Include sidebar stats so the shared sidebar renders without missing variables
    try:
        ctx.update(build_sidebar_context())
    except Exception:
        # Keep page functional even if stats query fails
        pass
    return render(request, "tracker/label_rule_debugger.html", ctx)


from bs4 import BeautifulSoup
from pathlib import Path
from collections import defaultdict
import subprocess
import sys
import os
import json
import re
import html
import tempfile
from difflib import HtmlDiff
from datetime import datetime
from gmail_auth import get_gmail_service
from scripts.import_gmail_filters import (
    load_json,
    sanitize_to_regex_terms,
    make_or_pattern,
)


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
        name_to_id = {v: k for k, v in id_to_name.items()}
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
                    "job_alert": "job_alert",
                    "alert": "job_alert",
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
                    "job_alert",
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
            request, f"✅ Imported and updated {updated} filter(s) in patterns.json."
        )
        return redirect("import_gmail_filters_compare")

    ctx = {
        "filters": filters,
        "error": error,
        "gmail_label_prefix": gmail_label_prefix,
        "debug_mappings": debug_mappings,
        "unmapped_labels": unmapped_labels,
    }
    ctx.update(build_sidebar_context())
    return render(request, "tracker/import_gmail_filters_compare.html", ctx)


# --- IMPORTS ---
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import (
    F,
    Q,
    Count,
    Case,
    When,
    Value,
    IntegerField,
    CharField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Substr, StrIndex
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt

from bs4 import BeautifulSoup
from pathlib import Path
from collections import defaultdict
import subprocess
import sys
import os
import json
import re
import html
import tempfile

from gmail_auth import get_gmail_service
from scripts.import_gmail_filters import (
    load_json,
    sanitize_to_regex_terms,
    make_or_pattern,
)

# --- END IMPORTS ---


@login_required
def gmail_filters_labels_compare(request):
    """
    Fetch Gmail filter rules via the Gmail API, compare old/new regex patterns for message labels, and allow incremental update.
    Only filters whose added label names start with the prefix are considered.
    UI: checkboxes for each label, editable new patterns, and a button to update selected.
    """


# --- IMPORTS ---
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import (
    F,
    Q,
    Count,
    Case,
    When,
    Value,
    IntegerField,
    CharField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Substr, StrIndex
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt

from bs4 import BeautifulSoup
from pathlib import Path
from collections import defaultdict
import subprocess
import sys
import os
import json
import re
import html
import tempfile

# --- END IMPORTS ---


# --- Gmail Filters Label Patterns Compare ---
@login_required
def gmail_filters_labels_compare(request):
    """
    Fetch Gmail filter rules via the Gmail API, compare old/new regex patterns for message labels, and allow incremental update.
    Only filters whose added label names start with the prefix are considered.
    UI: checkboxes for each label, editable new patterns, and a button to update selected.
    """
    from gmail_auth import get_gmail_service
    from scripts.import_gmail_filters import (
        load_json,
        sanitize_to_regex_terms,
        make_or_pattern,
    )

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
            label = request.POST.get(f"label_{i}")
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
        name_to_id = {v: k for k, v in id_to_name.items()}
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
                        "job_alert": "job_alert",
                        "alert": "job_alert",
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
                        "job_alert",
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
    from .views import build_sidebar_context

    ctx.update(build_sidebar_context())
    return render(request, "tracker/gmail_filters_labels_compare.html", ctx)


from django.db.models.functions import Coalesce, Substr, StrIndex
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt

from bs4 import BeautifulSoup
from pathlib import Path
from collections import defaultdict
import subprocess
import sys
import os
import json
import re
import html
import tempfile

from db import PATTERNS_PATH
from tracker.models import (
    Company,
    Application,
    Message,
    IngestionStats,
    UnresolvedCompany,
    GmailFilterImportLog,
)
from tracker.models import DomainToCompany
from tracker.forms import ApplicationEditForm
from .forms_company import CompanyEditForm
from scripts.import_gmail_filters import (
    load_json,
    parse_filters,
    sanitize_to_regex_terms,
    make_or_pattern,
)
from gmail_auth import get_gmail_service


# --- Delete Company Page ---
@login_required
def delete_company(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    if request.method == "POST":
        company_name = company.name

        # Count related data before deletion
        message_count = Message.objects.filter(company=company).count()
        application_count = Application.objects.filter(company=company).count()

        # Delete all related messages, applications, etc.
        Message.objects.filter(company=company).delete()
        Application.objects.filter(company=company).delete()
        # Remove company itself
        company.delete()

        # Show detailed deletion info
        messages.success(request, f"✅ Company '{company_name}' deleted successfully.")
        messages.info(
            request,
            f"📊 Removed {message_count} messages and {application_count} applications.",
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
    ctx.update(build_sidebar_context())
    return render(request, "tracker/delete_company.html", ctx)


# --- Label Companies Page ---
@login_required
def label_companies(request):
    companies = Company.objects.order_by("name")
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
            selected_company = companies.get(id=selected_id)
        except Company.DoesNotExist:
            selected_company = None
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
                    latest_label in ("rejected", "rejection")
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

            # Get message count and (date, subject) list
            messages_qs = Message.objects.filter(company=selected_company).order_by(
                "-timestamp"
            )
            message_count = messages_qs.count()
            message_info_list = list(messages_qs.values_list("timestamp", "subject"))
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
                    if latest_label in ("rejected", "rejection"):
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
                    form.save()
                    # Upsert domain_to_company when complete
                    try:
                        name = (selected_company.name or "").strip()
                        domain = (selected_company.domain or "").strip().lower()
                        if name and domain:
                            # Normalize domain
                            for prefix in ("http://", "https://"):
                                if domain.startswith(prefix):
                                    domain = domain[len(prefix) :]
                            if domain.startswith("www."):
                                domain = domain[4:]
                            if "." in domain:
                                DomainToCompany.objects.update_or_create(
                                    domain=domain, defaults={"company": name}
                                )
                    except Exception as e:
                        # Non-fatal; continue with redirect
                        print(f"⚠️ Failed to upsert DomainToCompany: {e}")
                    messages.success(
                        request, f"✅ Saved changes for {selected_company.name}."
                    )
                    return redirect(f"/label_companies/?company={selected_company.id}")
            else:
                form = CompanyEditForm(instance=selected_company)

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
            apps_moved = Application.objects.filter(company__in=duplicates).update(
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
    ctx.update(build_sidebar_context())
    return render(request, "tracker/merge_companies.html", ctx)


from datetime import timedelta, datetime

python_path = sys.executable
ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")


def build_sidebar_context():
    companies_count = Company.objects.count()
    applications_count = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()
    return {
        "companies": companies_count,
        "applications": applications_count,
        "applications_count": applications_count,
        "rejections_week": rejections_week,
        "interviews_week": interviews_week,
        "upcoming_interviews": upcoming_interviews,
        "latest_stats": latest_stats,
    }


# --- Log Viewer Page ---
@login_required
def log_viewer(request):
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
    ctx = build_sidebar_context()
    ctx.update(
        {
            "log_files": log_files,
            "selected_log": selected_log,
            "log_content": log_content,
        }
    )
    return render(request, "tracker/log_viewer.html", ctx)


@login_required
def company_threads(request):
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

    # Sidebar context
    companies_count = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/company_threads.html",
        {
            "companies": companies_count,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "company_list": companies,
            "selected_company": selected_company,
            "threads_by_subject": threads_by_subject,
        },
    )


@login_required
def manage_aliases(request):
    if not ALIAS_EXPORT_PATH.exists():
        ctx = {"suggestions": []}
        ctx.update(build_sidebar_context())
        return render(request, "tracker/manage_aliases.html", ctx)

    with open(ALIAS_EXPORT_PATH, "r", encoding="utf-8") as f:
        suggestions = json.load(f)

    ctx = {"suggestions": suggestions}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/manage_aliases.html", ctx)


@csrf_exempt
def approve_bulk_aliases(request):
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
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        form = ApplicationEditForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect("flagged_applications")
    else:
        form = ApplicationEditForm(instance=app)
    return render(request, "tracker/edit.html", {"form": form})


def flagged_applications(request):
    flagged = Application.objects.filter(
        models.Q(company="")
        | models.Q(company_source__in=["none", "ml_prediction", "sender_name_match"])
    ).order_by("-first_sent")[:100]

    return render(request, "tracker/flagged.html", {"applications": flagged})


@login_required
def dashboard(request):
    def clean_html(raw_html):
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return str(soup)

    companies = Company.objects.count()
    companies_list = Company.objects.all()
    unresolved_companies = UnresolvedCompany.objects.filter(reviewed=False).order_by(
        "-timestamp"
    )[:50]

    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")

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
    earliest_app = Application.objects.order_by("sent_date").first()
    # Default: use earliest application date
    app_start_date = earliest_app.sent_date if earliest_app else None
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
    import json
    from .models import MessageLabel
    from django.core.exceptions import ValidationError
    import re

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
        allowed_labels = set(MessageLabel.objects.values_list("label", flat=True))
        for entry in config:
            label = entry.get("label")
            display_name = entry.get("display_name")
            color = entry.get("color")
            # Validate label
            if label not in allowed_labels:
                continue
            # Validate color
            if not is_valid_color(color):
                color = "#2563eb"  # fallback to default
            plot_series_config.append(
                {
                    "key": label,  # Add key field for chart logic
                    "label": label,
                    "display_name": display_name,
                    "color": color,
                    "ml_label": label,  # use label as ml_label for consistency
                }
            )
    except Exception as e:
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
            {
                "label": "ghosted",
                "display_name": "Ghosted",
                "color": "#a3a3a3",
                "ml_label": "ghosted",
            },
            {
                "label": "job_alert",
                "display_name": "Job Alert",
                "color": "#eab308",
                "ml_label": "job_alert",
            },
        ]

    # Now build date list
    if app_start_date:
        app_end_date = now().date()
        app_num_days = (app_end_date - app_start_date).days + 1
        app_date_list = [
            app_start_date + timedelta(days=i) for i in range(app_num_days)
        ]
        app_qs = Application.objects.filter(sent_date__gte=app_start_date)
    else:
        app_date_list = []
        app_qs = Application.objects.none()

    # Build chart data dynamically based on configured series
    chart_series_data = []
    msg_qs = (
        Message.objects.filter(timestamp__date__gte=app_start_date)
        if app_date_list
        else Message.objects.none()
    )

    for series in plot_series_config:
        ml_label = series["ml_label"]
        # Check if this is an application-based series or message-based series
        if ml_label == "job_application":
            # Applications per day
            apps_by_day = app_qs.values("sent_date").annotate(count=models.Count("id"))
            apps_map = {r["sent_date"]: r["count"] for r in apps_by_day}
            data = [apps_map.get(d, 0) for d in app_date_list]
        elif ml_label == "rejected":
            # Rejections per day
            rejs_by_day = (
                app_qs.exclude(rejection_date=None)
                .values("rejection_date")
                .annotate(count=models.Count("id"))
            )
            rejs_map = {r["rejection_date"]: r["count"] for r in rejs_by_day}
            data = [rejs_map.get(d, 0) for d in app_date_list]
        elif ml_label == "interview_invite":
            # Interviews per day
            ints_by_day = (
                app_qs.exclude(interview_date=None)
                .values("interview_date")
                .annotate(count=models.Count("id"))
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

    return render(
        request,
        "tracker/dashboard.html",
        {
            "companies": companies,
            "companies_list": companies_list,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
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
        },
    )


def company_detail(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    applications = Application.objects.filter(company=company)
    messages = Message.objects.filter(company=company).order_by("timestamp")
    ctx = {"company": company, "applications": applications, "messages": messages}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/company_detail.html", ctx)


def extract_body_content(raw_html):
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script/style/noscript
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Extract body content if present
    body = soup.body
    return str(body) if body else soup.get_text(separator=" ", strip=True)


def label_applications(request):
    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith("label_") and value:
                app_id = int(key.split("_")[1])
                try:
                    app = Application.objects.get(pk=app_id)
                    app.ml_label = value
                    app.reviewed = True
                    app.save()
                except Message.DoesNotExist:
                    continue

        return redirect("label_applications")

    apps = Application.objects.filter(reviewed=False).order_by("sent_date")[:50]
    ctx = {"applications": apps}
    ctx.update(build_sidebar_context())
    return render(request, "tracker/label_applications.html", ctx)


@login_required
def label_messages(request):
    """Bulk message labeling interface with checkboxes"""
    training_output = None

    # Handle POST - Bulk label selected messages
    if request.method == "POST":
        action = request.POST.get("action")

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
                    apps_updated = Application.objects.filter(
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

                # Check if we should retrain
                labeled_count = Message.objects.filter(reviewed=True).count()
                if labeled_count % 20 == 0:
                    messages.info(request, "🔄 Triggering model retraining...")
                    try:
                        subprocess.Popen([python_path, "train_model.py"])
                        messages.success(
                            request, "✅ Model retraining started in background"
                        )
                    except Exception as e:
                        messages.warning(request, f"⚠️ Could not start retraining: {e}")
            else:
                messages.warning(request, "⚠️ Please select messages and a label")

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
    sort = request.GET.get(
        "sort", ""
    )  # subject, company, confidence, sender_domain, date
    order = request.GET.get("order", "asc")  # asc, desc

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

    # Apply search filter (searches subject, body, and sender)
    if search_query:
        qs = qs.filter(
            Q(subject__icontains=search_query)
            | Q(body__icontains=search_query)
            | Q(sender__icontains=search_query)
        )

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
        qs = qs.order_by("-timestamp" if is_desc else "timestamp")
    else:
        # Fallback: order by confidence priority similar to previous behavior
        if filter_confidence in ("high", "medium"):
            qs = qs.order_by(F("confidence").desc(nulls_last=True), "-timestamp")
        else:
            qs = qs.order_by(F("confidence").asc(nulls_first=True), "timestamp")

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
        "job_alert",
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

    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/label_messages.html",
        {
            "message_list": messages_page,
            "filter_label": filter_label,
            "filter_confidence": filter_confidence,
            "filter_company": filter_company,
            "filter_reviewed": filter_reviewed,
            "search_query": search_query,
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
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "filter_reviewed": filter_reviewed,
        },
    )


@login_required
def metrics(request):
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
        "job_alert",
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

    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/metrics.html",
        {
            "metrics": metrics,
            "training_output": training_output,
            "label_breakdown": label_breakdown,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
            "chart_labels": chart_labels,
            "chart_inserted": chart_inserted,
            "chart_skipped": chart_skipped,
            "chart_ignored": chart_ignored,
        },
    )


@csrf_exempt
@login_required
def retrain_model(request):
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
    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/metrics.html",
        {
            "metrics": {},
            "training_output": training_output,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        },
    )


import re
import html


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
        is_valid, error = validate_regex_pattern(value)
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
        file_type = request.POST.get("file_type")

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
                    "job_alert",
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

                import re

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

    # Sidebar context
    companies = Company.objects.count()
    applications = Application.objects.count()
    rejections_week = Application.objects.filter(
        rejection_date__gte=now() - timedelta(days=7)
    ).count()
    interviews_week = Application.objects.filter(
        interview_date__gte=now() - timedelta(days=7)
    ).count()
    upcoming_interviews = Application.objects.filter(
        interview_date__gte=now()
    ).order_by("interview_date")
    latest_stats = IngestionStats.objects.order_by("-date").first()

    return render(
        request,
        "tracker/json_file_viewer.html",
        {
            "patterns_data": patterns_data,
            "companies_data": companies_data,
            "success_message": success_message,
            "error_message": error_message,
            "validation_errors": validation_errors,
            "companies": companies,
            "applications": applications,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        },
    )


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
    ctx.update(build_sidebar_context())

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
                name_to_id = {v: k for k, v in id_to_name.items()}
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
                                "job_alert",
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
    ctx.update(build_sidebar_context())
    return render(request, "tracker/configure_settings.html", ctx)
