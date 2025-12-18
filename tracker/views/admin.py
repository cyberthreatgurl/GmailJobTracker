"""Admin views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.http import JsonResponse, StreamingHttpResponse
from tracker.models import IngestionStats, Message
from tracker.services import StatsService, CompanyService
from tracker.views.helpers import sanitize_string, validate_domain
from parser import ingest_message
from scripts.import_gmail_filters import load_json, sanitize_to_regex_terms, make_or_pattern
from gmail_auth import get_gmail_service

python_path = sys.executable


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
    ctx = {
        "log_files": log_files,
        "selected_log": selected_log,
        "log_content": log_content,
    }
    return render(request, "tracker/log_viewer.html", ctx)



@csrf_exempt

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



@login_required
def reingest_admin(request):
    """Run the ingest_gmail command with options and show output."""
    base_dir = Path(__file__).resolve().parents[2]
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
    base_dir = Path(__file__).resolve().parents[2]
    days_back = request.GET.get("days_back")
    force = request.GET.get("force") == "true"
    reparse_all = request.GET.get("reparse_all") == "true"

    cmd = [
        sys.executable,
        "-u",  # unbuffered
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


__all__ = ['log_viewer', 'retrain_model', 'json_file_viewer', 'reingest_admin', 'reingest_stream', 'configure_settings']
