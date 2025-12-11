"""Messages views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q, Count, F
from tracker.models import Message, Company
from tracker.services import MessageService


import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q, Count, F
from tracker.models import Message, Company
from tracker.services import MessageService


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
                from tracker.label_helpers import label_message_and_propagate

                for msg_id in selected_ids:
                    try:
                        msg = Message.objects.get(pk=msg_id)
                        # Use centralized helper to save+propagate label changes
                        # This is a manual/admin action — allow overwriting reviewed flags
                        label_message_and_propagate(msg, bulk_label, confidence=1.0, overwrite_reviewed=True)
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
                    from parser import ingest_message, parse_subject, predict_with_fallback, predict_subject_type

                    service = get_gmail_service()
                    success_count = 0
                    error_count = 0

                    for db_id in selected_ids:
                        try:
                            msg = Message.objects.get(pk=db_id)
                            gmail_msg_id = msg.msg_id

                            # Clear reviewed flag when re-ingesting from the Label Messages UI
                            try:
                                msg.reviewed = False
                                msg.save(update_fields=["reviewed"])
                                if msg.thread_id:
                                    ThreadTracking.objects.filter(thread_id=msg.thread_id).update(reviewed=False)
                            except Exception:
                                logger.exception(f"Failed to clear reviewed for db id {db_id}")

                            # Audit: record UI-initiated clear for traceability (selected reingest)
                            try:
                                audit_path = Path("logs") / "clear_reviewed_audit.log"
                                audit_path.parent.mkdir(parents=True, exist_ok=True)
                                entry = {
                                    "ts": now().isoformat(),
                                    "user": request.user.username if hasattr(request, "user") else "unknown",
                                    "action": "ui_reingest_clear",
                                    "source": "reingest_selected",
                                    "db_id": db_id,
                                    "msg_id": gmail_msg_id,
                                    "thread_id": msg.thread_id if msg else None,
                                    "company_id": msg.company.id if getattr(msg, "company", None) else None,
                                    "pid": os.getpid(),
                                }
                                with open(audit_path, "a", encoding="utf-8") as af:
                                    af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                                # Also persist to DB for easier querying
                                try:
                                    AuditEvent.objects.create(
                                        user=entry.get("user"),
                                        action=entry.get("action"),
                                        source=entry.get("source"),
                                        msg_id=entry.get("msg_id"),
                                        db_id=entry.get("db_id"),
                                        thread_id=entry.get("thread_id"),
                                        company_id=entry.get("company_id"),
                                        details=json.dumps(entry, ensure_ascii=False),
                                        pid=entry.get("pid"),
                                    )
                                except Exception:
                                    logger.exception("Failed to write AuditEvent DB record for ui_reingest_clear (selected)")
                            except Exception as e:
                                logger.exception("Failed to write audit log for UI reingest clear (selected)")
                                try:
                                    import traceback

                                    audit_path = Path("logs") / "clear_reviewed_audit.log"
                                    audit_path.parent.mkdir(parents=True, exist_ok=True)
                                    entry = {
                                        "ts": now().isoformat(),
                                        "user": request.user.username if hasattr(request, "user") else "unknown",
                                        "action": "ui_reingest_clear",
                                        "source": "reingest_selected",
                                        "db_id": db_id,
                                        "msg_id": gmail_msg_id,
                                        "error": str(e),
                                        "trace": traceback.format_exc(),
                                    }
                                    with open(audit_path, "a", encoding="utf-8") as af:
                                        af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                                except Exception:
                                    logger.exception("Also failed to write error audit for UI reingest clear (selected)")

                            # Suppress auto-mark-reviewed during this UI-initiated re-ingest
                            try:
                                os.environ["SUPPRESS_AUTO_REVIEW"] = "1"
                                # Check if this is an uploaded .eml file (ID starts with eml_)
                                if gmail_msg_id.startswith("eml_"):
                                    # Re-classify from stored body text
                                    # Re-run classification
                                    result_dict = predict_with_fallback(
                                        predict_subject_type,
                                        msg.subject,
                                        msg.body or "",
                                        sender=msg.sender
                                    )
                                    ml_label = result_dict.get("label", "noise")
                                    ml_confidence = result_dict.get("confidence", 0.0)
                                    
                                    # Re-parse company
                                    sender_domain = msg.sender.split("@")[-1].split(">")[0] if "@" in msg.sender else ""
                                    parse_result = parse_subject(
                                        msg.subject,
                                        msg.body or "",
                                        msg.sender,
                                        sender_domain
                                    )
                                    
                                    # Extract company
                                    company = None
                                    if isinstance(parse_result, dict):
                                        company = parse_result.get("company") or parse_result.get("predicted_company")
                                    elif isinstance(parse_result, str):
                                        company = parse_result
                                    
                                    # Apply internal referral override
                                    if isinstance(parse_result, dict) and parse_result.get("label") == "other" and ml_label in ("referral", "interview_invite"):
                                        from parser import _map_company_by_domain
                                        if sender_domain and company:
                                            mapped_domain_company = _map_company_by_domain(sender_domain)
                                            if mapped_domain_company and mapped_domain_company.lower() == company.lower():
                                                ml_label = "other"
                                    
                                    # Apply internal recruiter override - check original ML prediction
                                    # Only override to 'other' for generic spam, preserve meaningful labels
                                    original_ml_label = result_dict.get("ml_label") or result_dict.get("label")
                                    if original_ml_label == "head_hunter":
                                        from parser import _map_company_by_domain, HEADHUNTER_DOMAINS
                                        if sender_domain and sender_domain not in HEADHUNTER_DOMAINS:
                                            mapped_company = _map_company_by_domain(sender_domain)
                                            if mapped_company and ml_label not in ("interview_invite", "rejection", "job_application", "offer"):
                                                ml_label = "other"
                                    
                                    # Check if sender domain is in personal domains list - override to noise
                                    from parser import PERSONAL_DOMAINS
                                    if sender_domain and sender_domain.lower() in PERSONAL_DOMAINS:
                                        ml_label = "noise"
                                    
                                    # Update message
                                    msg.ml_label = ml_label
                                    msg.confidence = ml_confidence
                                    if company:
                                        company_obj, _ = Company.objects.get_or_create(name=company)
                                        msg.company = company_obj
                                    msg.save()
                                    result = "skipped"  # Mark as processed
                                else:
                                    # Regular Gmail message - fetch from API
                                    result = ingest_message(service, gmail_msg_id)
                            finally:
                                try:
                                    del os.environ["SUPPRESS_AUTO_REVIEW"]
                                except Exception:
                                    pass
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

        elif action == "clear_reviewed":
            # Clear the reviewed flag for selected messages so they can be re-ingested
            selected_ids = request.POST.getlist("selected_messages")

            if selected_ids:
                # Update Message.reviewed=False
                updated_count = Message.objects.filter(pk__in=selected_ids).update(reviewed=False)

                # Also clear ThreadTracking.reviewed for affected threads
                thread_ids = (
                    Message.objects.filter(pk__in=selected_ids)
                    .exclude(thread_id__isnull=True)
                    .values_list("thread_id", flat=True)
                )
                if thread_ids:
                    apps_updated = ThreadTracking.objects.filter(thread_id__in=list(thread_ids)).update(reviewed=False)
                else:
                    apps_updated = 0

                messages.success(
                    request,
                    f"✅ Cleared reviewed flag for {updated_count} message(s)"
                    + (f" and {apps_updated} application(s)" if apps_updated else ""),
                )
            else:
                messages.warning(request, "⚠️ Please select one or more messages to clear review state")

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



__all__ = ['label_applications', 'label_messages']
