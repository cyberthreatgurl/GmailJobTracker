"""Companies views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q, Count, F, Case, When, Value
from django.db.models.functions import Lower
from django.utils.timezone import now
from parser import parse_subject, normalize_company_name
from tracker.models import (
    Company,
    Message,
    ThreadTracking,
    UnresolvedCompany,
    AuditEvent,
)
from tracker.services import CompanyService
from tracker.forms import CompanyEditForm
from tracker.views.helpers import build_sidebar_context
from db import PATTERNS_PATH
from scripts.import_gmail_filters import load_json

# Module-level constants
python_path = sys.executable
logger = logging.getLogger(__name__)


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


@login_required
def label_companies(request):
    """List companies for labeling and provide quick actions (create/select/update)."""
    from urllib.parse import quote
    
    # Quick Add Company action - redirect to new company form instead of creating immediately
    if request.method == "POST" and request.POST.get("action") == "quick_add_company":
        from tracker.services.company_scraper import scrape_company_info, CompanyScraperError
        from urllib.parse import urlparse
        
        homepage_url = request.POST.get("homepage_url", "").strip()
        if not homepage_url:
            messages.error(request, "❌ Please enter a homepage URL.")
            return redirect("label_companies")
        
        # Add https:// if missing
        if not homepage_url.startswith(("http://", "https://")):
            homepage_url = "https://" + homepage_url
        
        # Validate URL syntax
        try:
            parsed = urlparse(homepage_url)
            if not parsed.netloc:
                messages.error(request, "❌ Invalid URL format. Please enter a valid URL.")
                return redirect("label_companies")
        except Exception:
            messages.error(request, "❌ Invalid URL format. Please enter a valid URL.")
            return redirect("label_companies")
        
        # Scrape company info
        try:
            scraped_data = scrape_company_info(homepage_url, timeout=10)
            company_name = scraped_data.get("name", "")
            domain = scraped_data.get("domain", "")
            career_url = scraped_data.get("career_url", "")
            
            # Check if company already exists in database by name or domain
            existing = None
            if company_name:
                existing = Company.objects.filter(name__iexact=company_name).first()
            if not existing and domain:
                existing = Company.objects.filter(domain__iexact=domain).first()
            
            if existing:
                messages.info(
                    request, f"ℹ️ Company '{existing.name}' already exists in database."
                )
                return redirect(f"/label_companies/?company={existing.id}")
            
            # Check if company exists in companies.json
            companies_json_path = Path("json/companies.json")
            if companies_json_path.exists():
                try:
                    with open(companies_json_path, "r", encoding="utf-8") as f:
                        companies_json_data = json.load(f)
                    
                    found_in_json = None
                    
                    # Check if scraped name is in known companies list
                    if company_name and "known" in companies_json_data:
                        for known_name in companies_json_data["known"]:
                            if known_name.lower() == company_name.lower():
                                found_in_json = known_name
                                break
                    
                    # Check if domain maps to a known company
                    if not found_in_json and domain and "domain_to_company" in companies_json_data:
                        if domain in companies_json_data["domain_to_company"]:
                            found_in_json = companies_json_data["domain_to_company"][domain]
                    
                    if found_in_json:
                        # Company exists in companies.json - check if Company record exists
                        existing = Company.objects.filter(name__iexact=found_in_json).first()
                        if existing:
                            messages.info(
                                request, f"ℹ️ Company '{existing.name}' already exists (found in companies.json)."
                            )
                            return redirect(f"/label_companies/?company={existing.id}")
                        else:
                            # Create Company record from companies.json entry
                            new_company = Company.objects.create(
                                name=found_in_json,
                                domain=domain or "",
                                homepage=homepage_url,
                                career_url=career_url or "",
                                confidence=1.0,
                                first_contact=now(),
                                last_contact=now(),
                                status="application"
                            )
                            messages.success(
                                request, f"✅ Created company '{new_company.name}' from known companies list."
                            )
                            return redirect(f"/label_companies/?company={new_company.id}")
                
                except Exception as e:
                    # If companies.json check fails, continue with normal flow
                    logger.exception(f"Failed to check companies.json: {e}")
            
            # Redirect to new company form with scraped data
            params = []
            if company_name:
                params.append(f"new_company_name={quote(company_name)}")
            if homepage_url:
                params.append(f"homepage={quote(homepage_url)}")
            if domain:
                params.append(f"domain={quote(domain)}")
            if career_url:
                params.append(f"career_url={quote(career_url)}")
            
            redirect_url = f"/label_companies/?{'&'.join(params)}"
            messages.success(request, f"✅ Scraped company info from {domain}. Review and save below.")
            return redirect(redirect_url)
            
        except CompanyScraperError as e:
            messages.error(request, f"❌ Failed to scrape company info: {e}")
            # Still allow manual entry by redirecting to form with just the URL
            return redirect(f"/label_companies/?homepage={quote(homepage_url)}")
        except Exception as e:
            messages.error(request, f"❌ Error scraping company info: {e}")
            return redirect("label_companies")

    # Exclude headhunter companies from the dropdown
    companies = Company.objects.exclude(status="headhunter").order_by(Lower("name"))
    # Preserve selected company on POST actions as well
    selected_id = request.GET.get("company") or request.POST.get("company")
    selected_company = None
    latest_label = None
    last_message_ts = None
    days_since_last_message = None
    
    # Check for new company creation mode (Quick Add prefill)
    new_company_name = request.GET.get("new_company_name", "").strip()
    prefill_homepage = request.GET.get("homepage", "").strip()
    prefill_domain = request.GET.get("domain", "").strip()
    prefill_career_url = request.GET.get("career_url", "").strip()
    creating_new_company = bool(new_company_name or prefill_homepage)
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
            alias = ""
            try:
                if companies_json_path.exists():
                    with open(companies_json_path, "r", encoding="utf-8") as f:
                        companies_json_data = json.load(f)
                        career_url = companies_json_data.get("JobSites", {}).get(
                            selected_company.name, ""
                        )
                        # Load alias for this company (reverse lookup in aliases dict)
                        aliases_dict = companies_json_data.get("aliases", {})
                        for alias_name, canonical_name in aliases_dict.items():
                            if canonical_name == selected_company.name:
                                alias = alias_name
                                break
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
                # Re-ingest messages for selected company
                if request.POST.get("action") == "reingest_company":
                    try:
                        from gmail_auth import get_gmail_service
                        from parser import ingest_message

                        service = get_gmail_service()
                        if not service:
                            messages.error(
                                request, "❌ Failed to initialize Gmail service."
                            )
                        else:
                            # Find all message IDs for this company
                            # Include messages currently assigned to this company
                            company_messages_query = Message.objects.filter(
                                company=selected_company
                            )

                            # Also include messages from company's domain or ATS domain
                            domains_to_check = []
                            if selected_company.domain:
                                domains_to_check.append(selected_company.domain)
                            if selected_company.ats:
                                domains_to_check.append(selected_company.ats)

                            # Build query to include sender domains
                            if domains_to_check:
                                from django.db.models import Q

                                domain_query = Q()
                                for domain in domains_to_check:
                                    domain_query |= Q(sender__icontains=f"@{domain}")

                                # Combine: messages assigned to company OR from company domains
                                company_messages_query = Message.objects.filter(
                                    Q(company=selected_company) | domain_query
                                ).distinct()

                            company_messages = company_messages_query.values(
                                "msg_id", "subject", "ml_label"
                            )

                            processed = 0
                            updated_labels = 0
                            errors = 0

                            for msg_info in company_messages[
                                :1000
                            ]:  # Limit to avoid timeout
                                try:
                                    old_label = msg_info["ml_label"]
                                    # Clear reviewed flag for messages reingested from the UI
                                    try:
                                        mobj = Message.objects.filter(
                                            msg_id=msg_info["msg_id"]
                                        ).first()
                                        if mobj:
                                            mobj.reviewed = False
                                            mobj.save(update_fields=["reviewed"])
                                            # Also clear ThreadTracking reviewed state for the thread
                                            if mobj.thread_id:
                                                ThreadTracking.objects.filter(
                                                    thread_id=mobj.thread_id
                                                ).update(reviewed=False)
                                    except Exception:
                                        # Best-effort: continue even if clearing fails
                                        logger.exception(
                                            f"Failed to clear reviewed for {msg_info['msg_id']}"
                                        )

                                    # Audit: record UI-initiated clear for traceability (batch/company reingest)
                                    try:
                                        audit_path = (
                                            Path("logs") / "clear_reviewed_audit.log"
                                        )
                                        audit_path.parent.mkdir(
                                            parents=True, exist_ok=True
                                        )
                                        entry = {
                                            "ts": now().isoformat(),
                                            "user": (
                                                request.user.username
                                                if hasattr(request, "user")
                                                else "unknown"
                                            ),
                                            "action": "ui_reingest_clear",
                                            "source": "reingest_company",
                                            "msg_id": msg_info["msg_id"],
                                            "company": (
                                                selected_company.name
                                                if selected_company
                                                else None
                                            ),
                                            "company_id": (
                                                selected_company.id
                                                if selected_company
                                                else None
                                            ),
                                            "thread_id": msg_info.get("thread_id"),
                                            "db_id": msg_info.get("id"),
                                            "pid": os.getpid(),
                                        }
                                        with open(
                                            audit_path, "a", encoding="utf-8"
                                        ) as af:
                                            af.write(
                                                json.dumps(entry, ensure_ascii=False)
                                                + "\n"
                                            )
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
                                                details=json.dumps(
                                                    entry, ensure_ascii=False
                                                ),
                                                pid=entry.get("pid"),
                                            )
                                        except Exception:
                                            logger.exception(
                                                "Failed to write AuditEvent DB record for ui_reingest_clear"
                                            )
                                    except Exception as e:
                                        # Include stack trace in logger; also write a minimal audit entry with error
                                        logger.exception(
                                            "Failed to write audit log for UI reingest clear"
                                        )
                                        try:
                                            import traceback

                                            audit_path = (
                                                Path("logs")
                                                / "clear_reviewed_audit.log"
                                            )
                                            audit_path.parent.mkdir(
                                                parents=True, exist_ok=True
                                            )
                                            entry = {
                                                "ts": now().isoformat(),
                                                "user": (
                                                    request.user.username
                                                    if hasattr(request, "user")
                                                    else "unknown"
                                                ),
                                                "action": "ui_reingest_clear",
                                                "source": "reingest_company",
                                                "msg_id": msg_info["msg_id"],
                                                "error": str(e),
                                                "trace": traceback.format_exc(),
                                            }
                                            with open(
                                                audit_path, "a", encoding="utf-8"
                                            ) as af:
                                                af.write(
                                                    json.dumps(
                                                        entry, ensure_ascii=False
                                                    )
                                                    + "\n"
                                                )
                                            try:
                                                AuditEvent.objects.create(
                                                    user=entry.get("user"),
                                                    action=entry.get("action"),
                                                    source=entry.get("source"),
                                                    msg_id=entry.get("msg_id"),
                                                    details=json.dumps(
                                                        entry, ensure_ascii=False
                                                    ),
                                                    error=entry.get("error"),
                                                    trace=entry.get("trace"),
                                                )
                                            except Exception:
                                                logger.exception(
                                                    "Failed to write fallback AuditEvent DB record for ui_reingest_clear"
                                                )
                                        except Exception:
                                            logger.exception(
                                                "Also failed to write error audit for UI reingest clear"
                                            )

                                    # Suppress auto-mark-reviewed during this UI-initiated re-ingest
                                    try:
                                        os.environ["SUPPRESS_AUTO_REVIEW"] = "1"
                                        ingest_message(service, msg_info["msg_id"])
                                    finally:
                                        try:
                                            del os.environ["SUPPRESS_AUTO_REVIEW"]
                                        except Exception:
                                            pass

                                    # Check if label changed
                                    updated_msg = Message.objects.get(
                                        msg_id=msg_info["msg_id"]
                                    )
                                    if updated_msg.ml_label != old_label:
                                        updated_labels += 1

                                    processed += 1
                                except Exception as e:
                                    errors += 1
                                    logger.error(
                                        f"Error re-ingesting {msg_info['msg_id']}: {e}"
                                    )

                            messages.success(
                                request,
                                f"✅ Re-ingested {processed} messages for {selected_company.name}. "
                                f"{updated_labels} labels updated. {errors} errors.",
                            )
                    except Exception as e:
                        messages.error(request, f"⚠️ Error during re-ingestion: {e}")
                        logger.exception("Re-ingestion error")

                    return redirect(f"/label_companies/?company={selected_company.id}")

                # Populate company info from homepage
                if request.POST.get("action") == "populate_from_homepage":
                    homepage_url = request.POST.get("homepage", "").strip()
                    if not homepage_url:
                        messages.error(request, "❌ Please enter a homepage URL first.")
                    else:
                        try:
                            from tracker.services.company_scraper import scrape_company_info, CompanyScraperError
                            
                            scraped_data = scrape_company_info(homepage_url)
                            
                            # Create a form with the scraped data
                            form_data = {
                                "name": scraped_data.get("name", selected_company.name),
                                "domain": scraped_data.get("domain", selected_company.domain),
                                "homepage": homepage_url,
                                "career_url": scraped_data.get("career_url", ""),
                                "ats": selected_company.ats or "",
                                "contact_name": selected_company.contact_name or "",
                                "contact_email": selected_company.contact_email or "",
                                "status": selected_company.status or "application",
                            }
                            form = CompanyEditForm(form_data, instance=selected_company)
                            
                            messages.success(
                                request,
                                f"✅ Successfully scraped company info from homepage. Review and click Save Changes to apply.",
                            )
                        except CompanyScraperError as e:
                            messages.error(request, f"❌ Failed to scrape homepage: {e}")
                            form = CompanyEditForm(instance=selected_company, initial={"career_url": career_url})
                        except Exception as e:
                            messages.error(request, f"❌ Unexpected error: {e}")
                            form = CompanyEditForm(instance=selected_company, initial={"career_url": career_url})
                    # Don't redirect - stay on page with populated form
                    
                # Quick action: mark as ghosted
                elif request.POST.get("action") == "save_notes":
                    # Save notes for the selected company
                    try:
                        notes_text = request.POST.get("notes", "").strip()
                        selected_company.notes = notes_text if notes_text else None
                        selected_company.save(update_fields=["notes"])
                        messages.success(
                            request,
                            f"✅ Notes saved for {selected_company.name}.",
                        )
                    except Exception as e:
                        messages.error(request, f"❌ Failed to save notes: {e}")
                    return redirect(f"/label_companies/?company={selected_company.id}")
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
                
                # Handle regular form submission (Save Changes)
                elif not request.POST.get("action"):  # No action means it's the main form
                    form = CompanyEditForm(request.POST, instance=selected_company)
                if form.is_valid():
                    # Get cleaned data before saving
                    career_url_input = (
                        form.cleaned_data.get("career_url") or ""
                    ).strip()
                    domain_input = (form.cleaned_data.get("domain") or "").strip()
                    ats_input = (form.cleaned_data.get("ats") or "").strip()
                    company_name = selected_company.name

                    # Save to companies.json
                    if company_name:
                        try:
                            companies_json_path = Path("json/companies.json")
                            if companies_json_path.exists():
                                with open(
                                    companies_json_path, "r", encoding="utf-8"
                                ) as f:
                                    companies_json_data = json.load(f)

                                # Track if any changes were made
                                changes_made = False

                                # Update career URL in JobSites
                                if "JobSites" not in companies_json_data:
                                    companies_json_data["JobSites"] = {}

                                current_value = companies_json_data["JobSites"].get(
                                    company_name
                                )
                                if career_url_input:
                                    # Set or update the career URL
                                    if current_value != career_url_input:
                                        companies_json_data["JobSites"][
                                            company_name
                                        ] = career_url_input
                                        changes_made = True
                                else:
                                    # Remove career URL if field is cleared
                                    if company_name in companies_json_data["JobSites"]:
                                        del companies_json_data["JobSites"][
                                            company_name
                                        ]
                                        changes_made = True

                                # Update domain in domain_to_company
                                if "domain_to_company" not in companies_json_data:
                                    companies_json_data["domain_to_company"] = {}

                                # Find and remove old domain mapping for this company
                                old_domain = None
                                for dom, comp in list(
                                    companies_json_data["domain_to_company"].items()
                                ):
                                    if comp == company_name:
                                        old_domain = dom
                                        break

                                if domain_input:
                                    # Set or update the domain mapping
                                    if old_domain and old_domain != domain_input:
                                        # Remove old mapping
                                        del companies_json_data["domain_to_company"][
                                            old_domain
                                        ]
                                        changes_made = True
                                    if (
                                        domain_input
                                        not in companies_json_data["domain_to_company"]
                                        or companies_json_data["domain_to_company"][
                                            domain_input
                                        ]
                                        != company_name
                                    ):
                                        companies_json_data["domain_to_company"][
                                            domain_input
                                        ] = company_name
                                        changes_made = True
                                else:
                                    # Remove domain mapping if field is cleared
                                    if old_domain:
                                        del companies_json_data["domain_to_company"][
                                            old_domain
                                        ]
                                        changes_made = True

                                # Update ATS domain in ats_domains
                                if "ats_domains" not in companies_json_data:
                                    companies_json_data["ats_domains"] = []

                                if ats_input:
                                    # Add ATS domain if not already present
                                    if (
                                        ats_input
                                        not in companies_json_data["ats_domains"]
                                    ):
                                        companies_json_data["ats_domains"].append(
                                            ats_input
                                        )
                                        changes_made = True
                                # Note: We don't remove ATS domains when cleared because they might be shared
                                # by multiple companies. Manual removal from companies.json is needed.

                                # Update alias in aliases
                                alias_input = (form.cleaned_data.get("alias") or "").strip()
                                if "aliases" not in companies_json_data:
                                    companies_json_data["aliases"] = {}

                                # Find and remove old alias for this company
                                old_alias = None
                                for alias_name, canonical_name in list(companies_json_data["aliases"].items()):
                                    if canonical_name == company_name:
                                        old_alias = alias_name
                                        break

                                if alias_input:
                                    # Set or update the alias mapping
                                    if old_alias and old_alias != alias_input:
                                        # Remove old alias
                                        del companies_json_data["aliases"][old_alias]
                                        changes_made = True
                                    if (
                                        alias_input not in companies_json_data["aliases"]
                                        or companies_json_data["aliases"][alias_input] != company_name
                                    ):
                                        companies_json_data["aliases"][alias_input] = company_name
                                        changes_made = True
                                else:
                                    # Remove alias if field is cleared
                                    if old_alias:
                                        del companies_json_data["aliases"][old_alias]
                                        changes_made = True

                                # Only write to file if changes were made
                                if changes_made:
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
                            messages.warning(
                                request, f"⚠️ Failed to save to companies.json: {e}"
                            )
                    form.save()
                    messages.success(request, "✅ Company details saved.")
                    return redirect(f"/label_companies/?company={selected_company.id}")
                # If invalid, fall through to render the bound form with errors
            else:
                # GET request: initialize form with current data, career URL and alias from companies.json
                form = CompanyEditForm(
                    instance=selected_company, initial={"career_url": career_url, "alias": alias}
                )

    # Handle new company creation mode (Quick Add prefill)
    if creating_new_company and not selected_company:
        if request.method == "POST":
            # Handle populate action for new company
            if request.POST.get("action") == "populate_from_homepage":
                homepage_url = request.POST.get("homepage", "").strip()
                if not homepage_url:
                    messages.error(request, "❌ Please enter a homepage URL first.")
                    form = CompanyEditForm(initial={"name": new_company_name})
                else:
                    try:
                        from tracker.services.company_scraper import scrape_company_info, CompanyScraperError
                        
                        scraped_data = scrape_company_info(homepage_url)
                        
                        # Create a form with the scraped data
                        form_data = {
                            "name": scraped_data.get("name", new_company_name),
                            "domain": scraped_data.get("domain", ""),
                            "homepage": homepage_url,
                            "career_url": scraped_data.get("career_url", ""),
                            "ats": "",
                            "contact_name": "",
                            "contact_email": "",
                            "status": "new",
                        }
                        form = CompanyEditForm(form_data)
                        
                        messages.success(
                            request,
                            f"✅ Successfully scraped company info. Review and click Create Company to save.",
                        )
                    except CompanyScraperError as e:
                        messages.error(request, f"❌ Failed to scrape homepage: {e}")
                        form = CompanyEditForm(initial={"name": new_company_name, "homepage": homepage_url})
                    except Exception as e:
                        messages.error(request, f"❌ Unexpected error: {e}")
                        form = CompanyEditForm(initial={"name": new_company_name, "homepage": homepage_url})
            # Handle create action
            elif request.POST.get("action") == "create_new_company":
                # User submitted the new company form
                form = CompanyEditForm(request.POST)
                if form.is_valid():
                    # Check if domain or homepage was provided
                    domain = form.cleaned_data.get("domain", "").strip()
                    homepage = form.cleaned_data.get("homepage", "").strip()
                    if not domain and not homepage:
                        messages.error(request, "❌ Please enter at least a domain or homepage before saving.")
                        # Form stays bound with submitted data for re-display
                    else:
                        # Create the company
                        new_company = form.save(commit=False)
                        new_company.confidence = 1.0
                        new_company.first_contact = now()
                        new_company.last_contact = now()
                        if not new_company.status:
                            new_company.status = "new"
                        new_company.save()
                        messages.success(request, f"✅ Company '{new_company.name}' created successfully!")
                        
                        # Save to companies.json (known array + domain mapping + career URL if provided)
                        try:
                            companies_json_path = Path("json/companies.json")
                            if companies_json_path.exists():
                                with open(companies_json_path, "r", encoding="utf-8") as f:
                                    companies_json_data = json.load(f)
                                
                                changes_made = False
                                
                                # Add to known array if not already present
                                if "known" not in companies_json_data:
                                    companies_json_data["known"] = []
                                if new_company.name not in companies_json_data["known"]:
                                    companies_json_data["known"].append(new_company.name)
                                    changes_made = True
                                
                                # Add domain mapping if domain was provided
                                if domain:
                                    if "domain_to_company" not in companies_json_data:
                                        companies_json_data["domain_to_company"] = {}
                                    if domain not in companies_json_data["domain_to_company"]:
                                        companies_json_data["domain_to_company"][domain] = new_company.name
                                        changes_made = True
                                
                                # Add career URL to JobSites if provided
                                career_url = form.cleaned_data.get("career_url", "").strip()
                                if career_url:
                                    if "JobSites" not in companies_json_data:
                                        companies_json_data["JobSites"] = {}
                                    if new_company.name not in companies_json_data["JobSites"]:
                                        companies_json_data["JobSites"][new_company.name] = career_url
                                        changes_made = True
                                    elif companies_json_data["JobSites"][new_company.name] != career_url:
                                        companies_json_data["JobSites"][new_company.name] = career_url
                                        changes_made = True
                                
                                # Add alias to aliases if provided
                                alias = form.cleaned_data.get("alias", "").strip()
                                if alias:
                                    if "aliases" not in companies_json_data:
                                        companies_json_data["aliases"] = {}
                                    if alias not in companies_json_data["aliases"]:
                                        companies_json_data["aliases"][alias] = new_company.name
                                        changes_made = True
                                    elif companies_json_data["aliases"][alias] != new_company.name:
                                        companies_json_data["aliases"][alias] = new_company.name
                                        changes_made = True
                                
                                if changes_made:
                                    with open(companies_json_path, "w", encoding="utf-8") as f:
                                        json.dump(companies_json_data, f, indent=2, ensure_ascii=False)
                        except Exception as e:
                            messages.warning(request, f"⚠️ Failed to save to companies.json: {e}")
                        
                        return redirect(f"/label_companies/?company={new_company.id}")
                # If form invalid, it stays bound with errors for re-display
        else:
            # GET request: show form with prefilled scraped data
            initial_data = {}
            if new_company_name:
                initial_data["name"] = new_company_name
            if prefill_homepage:
                initial_data["homepage"] = prefill_homepage
            if prefill_domain:
                initial_data["domain"] = prefill_domain
            if prefill_career_url:
                initial_data["career_url"] = prefill_career_url
            form = CompanyEditForm(initial=initial_data)

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
            "creating_new_company": creating_new_company,
            "new_company_name": new_company_name,
        }
    )
    return render(request, "tracker/label_companies.html", ctx)


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


# Constants for manage_domains function
ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
ALIAS_LOG_PATH = Path("alias_approvals.csv")
ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")


def manage_domains(request):
    """
    Domain management page for classifying email domains as personal, company, ATS, or headhunter.
    Extracts domains from ingested messages and allows bulk labeling.
    """
    from collections import Counter, defaultdict

    # Paths to JSON files
    companies_path = Path(__file__).parent.parent.parent / "json" / "companies.json"
    personal_domains_path = (
        Path(__file__).parent.parent.parent / "json" / "personal_domains.json"
    )

    # Load existing classifications
    companies_data = {}
    if companies_path.exists():
        with open(companies_path, "r", encoding="utf-8") as f:
            companies_data = json.load(f)

    personal_domains_data = {}
    if personal_domains_path.exists():
        with open(personal_domains_path, "r", encoding="utf-8") as f:
            personal_domains_data = json.load(f)

    domain_to_company = companies_data.get("domain_to_company", {})
    ats_domains = set(companies_data.get("ats_domains", []))
    headhunter_domains = set(companies_data.get("headhunter_domains", []))
    job_boards = set(companies_data.get("job_boards", []))
    personal_domains = set(personal_domains_data.get("domains", []))

    # Debug: compute counts for Job Boards vs rendered list to investigate Issue #28
    try:
        job_board_domains_db = (
            Company.objects.filter(status="job_board", domain__isnull=False)
            .values_list("domain", flat=True)
            .distinct()
        )
        job_board_domains_db = set(job_board_domains_db)
    except Exception:
        job_board_domains_db = set()

    try:
        job_board_badge_count = len(job_boards) if isinstance(job_boards, set) else 0
    except Exception:
        job_board_badge_count = 0

    # Write a small debug log entry for comparison
    try:
        dbg_path = Path("logs") / "manage_domains_debug.log"
        dbg_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": now().isoformat(),
            "user": getattr(getattr(request, "user", None), "username", "unknown"),
            "job_board_badge_count": job_board_badge_count,
            "job_board_db_distinct": sorted(job_board_domains_db),
            "job_board_db_count": len(job_board_domains_db),
        }
        # Also print to console to confirm execution path
        print("[manage_domains debug]", entry)
        with open(dbg_path, "a", encoding="utf-8") as df:
            df.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Handle POST requests for labeling
    reingest_summary = None
    # Expose debug counts in context for immediate UI verification
    debug_counts = {
        "job_board_badge_count": job_board_badge_count,
        "job_board_db_count": len(job_board_domains_db),
    }

    if request.method == "POST":
        action = request.POST.get("action")
        label_type = request.POST.get("label_type")

        if action == "sync_db_to_json":
            # Sync Company domains from database to companies.json
            try:
                synced_domains = 0
                synced_ats = 0
                skipped = 0

                # Get all companies with domains from database
                companies_with_domains = (
                    Company.objects.filter(domain__isnull=False)
                    .exclude(domain="")
                    .select_related()
                )

                # Define domains to skip (personal, receipts, etc.)
                skip_domains = {
                    "redditmail.com",
                    "dropbox.com",
                    "slack.com",
                    "stripe.com",
                    "clover.com",
                    "toasttab.com",
                    "invalidemail.com",
                    "indeed.com",
                    "ereceipt.usps.gov",
                    "govdelivery.dmv.virginia.gov",
                    "marketing.carmaxautofinance.com",
                    "info.wifionboard.com",
                    "estatement.apria.com",
                    "email.alaskaair.com",
                    "ops.sense.com",
                    "oracleheartva.com",
                    "osc.gov",
                    "peoplentech.com",
                    "rachelsfba.com",
                    "rmcweb.com",
                    "rokland.com",
                    "txn.getjobber.com",
                    "topsidefcu.org",
                    "virustotal.com",
                    "vec.virginia.gov",
                    "katorparks.com",
                    "jamhoff.com",
                    "app.slicelife.com",
                    "docusign.net",
                }

                for company in companies_with_domains:
                    domain = company.domain.strip().lower()

                    # Skip if already in companies.json or in skip list
                    if domain in domain_to_company or domain in skip_domains:
                        continue

                    # Skip if it's already an ATS domain
                    if domain in ats_domains:
                        continue

                    # Check if company is a headhunter
                    if company.status == "headhunter":
                        if domain not in headhunter_domains:
                            headhunter_domains.add(domain)
                            synced_domains += 1
                    else:
                        # Add to domain_to_company
                        domain_to_company[domain] = company.name
                        synced_domains += 1

                    # Also sync ATS domain if present
                    if company.ats and company.ats.strip():
                        ats_domain = company.ats.strip().lower()
                        if ats_domain not in ats_domains:
                            ats_domains.add(ats_domain)
                            synced_ats += 1

                # Save updated companies.json
                companies_data["domain_to_company"] = dict(
                    sorted(domain_to_company.items())
                )
                companies_data["ats_domains"] = sorted(ats_domains)
                companies_data["headhunter_domains"] = sorted(headhunter_domains)

                with open(companies_path, "w", encoding="utf-8") as f:
                    json.dump(companies_data, f, indent=2, ensure_ascii=False)

                messages.success(
                    request,
                    f"✅ Synced {synced_domains} company domain(s) and {synced_ats} ATS domain(s) from database to companies.json",
                )
                return redirect("manage_domains")

            except Exception as e:
                messages.error(request, f"❌ Error syncing domains: {e}")
                logger.exception("Domain sync error")

        elif action == "reingest_domains":
            # Re-ingest messages from specific domains
            reingest_filter = request.POST.get("reingest_filter", "personal")
            selected_domains = request.POST.getlist("domains")

            # Determine which domains to re-ingest
            domains_to_reingest = set()
            if reingest_filter == "personal":
                domains_to_reingest = personal_domains.copy()
            elif reingest_filter == "selected":
                domains_to_reingest = set(selected_domains)
            elif reingest_filter == "current_filter":
                # Re-ingest domains from the current filter view
                current_filter_param = request.POST.get("current_filter", "unlabeled")
                search_param = request.POST.get("search_query", "").strip().lower()

                # Get all domains from messages
                messages_qs = Message.objects.all()
                domain_counter = Counter()
                for msg in messages_qs.values("sender"):
                    sender = msg["sender"]
                    if "@" in sender:
                        email = sender
                        if "<" in sender and ">" in sender:
                            import re

                            email_matches = re.findall(r"<([^>]+@[^>]+)>", sender)
                            if email_matches:
                                email = email_matches[-1]
                        if "@" in email:
                            domain = email.split("@")[-1].lower()
                            if domain != "manual" and not domain.startswith("manual_"):
                                domain_counter[domain] += 1

                # Apply filter
                all_domain_list = list(domain_counter.keys())
                filtered_domains = []

                for domain in all_domain_list:
                    # Apply search filter
                    if search_param and search_param not in domain.lower():
                        continue

                    # Apply category filter
                    if current_filter_param == "unlabeled":
                        if (
                            domain not in personal_domains
                            and domain not in ats_domains
                            and domain not in headhunter_domains
                            and domain not in job_boards
                            and domain not in domain_to_company
                        ):
                            filtered_domains.append(domain)
                    elif (
                        current_filter_param == "personal"
                        and domain in personal_domains
                    ):
                        filtered_domains.append(domain)
                    elif (
                        current_filter_param == "company"
                        and domain in domain_to_company
                    ):
                        filtered_domains.append(domain)
                    elif current_filter_param == "ats" and domain in ats_domains:
                        filtered_domains.append(domain)
                    elif (
                        current_filter_param == "headhunter"
                        and domain in headhunter_domains
                    ):
                        filtered_domains.append(domain)
                    elif current_filter_param == "job_boards" and domain in job_boards:
                        filtered_domains.append(domain)
                    elif current_filter_param == "all":
                        filtered_domains.append(domain)

                domains_to_reingest = set(filtered_domains)
            elif reingest_filter == "all_labeled":
                domains_to_reingest = (
                    personal_domains
                    | ats_domains
                    | headhunter_domains
                    | job_boards
                    | set(domain_to_company.keys())
                )

            if not domains_to_reingest:
                messages.warning(request, "⚠️ No domains selected for re-ingestion.")
            else:
                try:
                    from gmail_auth import get_gmail_service
                    from parser import ingest_message

                    service = get_gmail_service()
                    if not service:
                        messages.error(
                            request, "❌ Failed to initialize Gmail service."
                        )
                    else:
                        # Find all messages from these domains
                        messages_to_reingest = []
                        for msg in Message.objects.all().values(
                            "msg_id", "sender", "subject", "ml_label"
                        ):
                            sender = msg["sender"]
                            if "@" in sender:
                                email = sender
                                if "<" in sender and ">" in sender:
                                    email = sender[
                                        sender.index("<") + 1 : sender.index(">")
                                    ]
                                domain = email.split("@")[-1].lower()

                                if domain in domains_to_reingest:
                                    messages_to_reingest.append(
                                        {
                                            "msg_id": msg["msg_id"],
                                            "subject": msg["subject"],
                                            "domain": domain,
                                            "old_label": msg["ml_label"],
                                        }
                                    )

                        # Re-ingest messages
                        processed = 0
                        updated_to_noise = 0
                        kept_as_other = 0
                        errors = 0
                        sample_updates = []

                        for msg_info in messages_to_reingest[
                            :1000
                        ]:  # Limit to 1000 to avoid timeout
                            try:
                                old_label = msg_info["old_label"]
                                ingest_message(service, msg_info["msg_id"])

                                # Check new label
                                updated_msg = Message.objects.get(
                                    msg_id=msg_info["msg_id"]
                                )
                                new_label = updated_msg.ml_label

                                processed += 1

                                if new_label == "noise" and old_label != "noise":
                                    updated_to_noise += 1
                                    if len(sample_updates) < 5:
                                        sample_updates.append(
                                            f"{msg_info['subject'][:50]} ({msg_info['domain']}) → noise"
                                        )
                                elif new_label == "other":
                                    kept_as_other += 1
                            except Exception as e:
                                errors += 1
                                logger.error(
                                    f"Error re-ingesting {msg_info['msg_id']}: {e}"
                                )

                        reingest_summary = {
                            "domains_processed": len(domains_to_reingest),
                            "messages_processed": processed,
                            "updated_to_noise": updated_to_noise,
                            "kept_as_other": kept_as_other,
                            "errors": errors,
                            "sample_updates": sample_updates,
                        }

                        messages.success(
                            request,
                            f"✅ Re-ingested {processed} messages from {len(domains_to_reingest)} domain(s). "
                            f"{updated_to_noise} updated to noise.",
                        )
                except Exception as e:
                    messages.error(request, f"⚠️ Error during re-ingestion: {e}")
                    logger.exception("Re-ingestion error")

        elif action == "bulk_label":
            domains = request.POST.getlist("domains")
            if not domains:
                messages.error(request, "⚠️ No domains selected.")
            elif not label_type:
                messages.error(request, "⚠️ No label type specified.")
            else:
                try:
                    # Remove from all categories first
                    for domain in domains:
                        personal_domains.discard(domain)
                        ats_domains.discard(domain)
                        headhunter_domains.discard(domain)
                        job_boards.discard(domain)
                        if domain in domain_to_company:
                            del domain_to_company[domain]

                    # Add to selected category
                    if label_type == "personal":
                        personal_domains.update(domains)
                    elif label_type == "ats":
                        ats_domains.update(domains)
                    elif label_type == "headhunter":
                        headhunter_domains.update(domains)
                    elif label_type == "job_boards":
                        job_boards.update(domains)
                    elif label_type == "company":
                        # Extract company from existing Message records for this domain
                        import re
                        from email.utils import parseaddr

                        for domain in domains:
                            if domain not in domain_to_company:
                                company_name = None

                                # Check if this is an ATS domain (e.g., otp.workday.com)
                                # ATS domains serve multiple companies and should not be labeled as "company"
                                is_ats = False
                                domain_lower = domain.lower()
                                for ats_root in ats_domains:
                                    if (
                                        domain_lower == ats_root
                                        or domain_lower.endswith(f".{ats_root}")
                                    ):
                                        is_ats = True
                                        break

                                if is_ats:
                                    # Don't label ATS domains as company - warn the user
                                    messages.warning(
                                        request,
                                        f"⚠️ {domain} appears to be an ATS domain (serves multiple companies). "
                                        f"Consider labeling it as 'ATS' instead.",
                                    )
                                    continue

                                # First, check if messages from this domain already have a company assigned
                                domain_messages = Message.objects.filter(
                                    sender__icontains=f"@{domain}",
                                    company__isnull=False,
                                ).select_related("company")[:5]

                                if domain_messages:
                                    # Check if multiple companies use this domain
                                    from collections import Counter

                                    companies = [
                                        msg.company.name
                                        for msg in domain_messages
                                        if msg.company
                                    ]
                                    if companies:
                                        company_counts = Counter(companies)
                                        # If more than one company with significant representation, it's likely an ATS
                                        if (
                                            len(company_counts) > 1
                                            and company_counts.most_common(2)[1][1] > 1
                                        ):
                                            messages.warning(
                                                request,
                                                f"⚠️ {domain} is used by multiple companies ({', '.join(company_counts.keys())}). "
                                                f"This may be an ATS domain. Consider labeling it as 'ATS' instead.",
                                            )
                                            continue
                                        company_name = company_counts.most_common(1)[0][
                                            0
                                        ]

                                # Fallback: Parse from sender display name
                                if not company_name:
                                    sender_messages = Message.objects.filter(
                                        sender__icontains=f"@{domain}"
                                    ).values("sender")[:5]
                                    for msg in sender_messages:
                                        sender = msg["sender"]
                                        # Extract display name from "Display Name <email@domain.com>"
                                        display_name, _ = parseaddr(sender)
                                        if display_name:
                                            # Clean up common suffixes
                                            cleaned = re.sub(
                                                r"\s*(Talent|Careers?|Jobs?|Recruiting|HR|Notifications?|Team|Hiring|Acquisition)\s*$",
                                                "",
                                                display_name,
                                                flags=re.IGNORECASE,
                                            ).strip()
                                            if cleaned and len(cleaned) > 2:
                                                company_name = cleaned
                                                break

                                # Final fallback: use the main domain name (not subdomain)
                                if not company_name:
                                    parts = domain.split(".")
                                    if len(parts) >= 2:
                                        # Use the second-to-last part (e.g., "brassring" from "trm.brassring.com")
                                        company_name = parts[-2].title()
                                    else:
                                        company_name = parts[0].title()

                                domain_to_company[domain] = company_name

                    # Save to JSON files
                    personal_domains_data["domains"] = sorted(personal_domains)
                    with open(personal_domains_path, "w", encoding="utf-8") as f:
                        json.dump(
                            personal_domains_data, f, indent=2, ensure_ascii=False
                        )

                    companies_data["domain_to_company"] = dict(
                        sorted(domain_to_company.items())
                    )
                    companies_data["ats_domains"] = sorted(ats_domains)
                    companies_data["headhunter_domains"] = sorted(headhunter_domains)
                    with open(companies_path, "w", encoding="utf-8") as f:
                        json.dump(companies_data, f, indent=2, ensure_ascii=False)

                    messages.success(
                        request, f"✅ Labeled {len(domains)} domain(s) as {label_type}."
                    )
                    return redirect("manage_domains")
                except Exception as e:
                    messages.error(request, f"⚠️ Error saving domain labels: {e}")

        elif action == "label_single":
            domain = request.POST.get("domain")
            if domain and label_type:
                try:
                    # Remove from all categories first
                    personal_domains.discard(domain)
                    ats_domains.discard(domain)
                    headhunter_domains.discard(domain)
                    job_boards.discard(domain)
                    if domain in domain_to_company:
                        del domain_to_company[domain]

                    # Add to selected category
                    if label_type == "personal":
                        personal_domains.add(domain)
                    elif label_type == "ats":
                        ats_domains.add(domain)
                    elif label_type == "headhunter":
                        headhunter_domains.add(domain)
                    elif label_type == "job_boards":
                        job_boards.add(domain)
                    elif label_type == "company":
                        # Extract company from existing Message records for this domain
                        import re
                        from email.utils import parseaddr

                        company_name = None

                        # Check if this is an ATS domain (e.g., otp.workday.com)
                        # ATS domains serve multiple companies and should not be labeled as "company"
                        is_ats = False
                        domain_lower = domain.lower()
                        for ats_root in ats_domains:
                            if domain_lower == ats_root or domain_lower.endswith(
                                f".{ats_root}"
                            ):
                                is_ats = True
                                break

                        if is_ats:
                            # Don't label ATS domains as company - warn the user
                            messages.warning(
                                request,
                                f"⚠️ {domain} appears to be an ATS domain (serves multiple companies). "
                                f"Consider labeling it as 'ATS' instead.",
                            )
                            return redirect(
                                f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                            )

                        # First, check if messages from this domain already have a company assigned
                        domain_messages = Message.objects.filter(
                            sender__icontains=f"@{domain}", company__isnull=False
                        ).select_related("company")[:5]

                        if domain_messages:
                            # Check if multiple companies use this domain
                            from collections import Counter

                            companies = [
                                msg.company.name
                                for msg in domain_messages
                                if msg.company
                            ]
                            if companies:
                                company_counts = Counter(companies)
                                # If more than one company with significant representation, it's likely an ATS
                                if (
                                    len(company_counts) > 1
                                    and company_counts.most_common(2)[1][1] > 1
                                ):
                                    messages.warning(
                                        request,
                                        f"⚠️ {domain} is used by multiple companies ({', '.join(company_counts.keys())}). "
                                        f"This may be an ATS domain. Consider labeling it as 'ATS' instead.",
                                    )
                                    return redirect(
                                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                                    )
                                company_name = company_counts.most_common(1)[0][0]

                        # Fallback: Parse from sender display name
                        if not company_name:
                            sender_messages = Message.objects.filter(
                                sender__icontains=f"@{domain}"
                            ).values("sender")[:5]
                            for msg in sender_messages:
                                sender = msg["sender"]
                                # Extract display name from "Display Name <email@domain.com>"
                                display_name, _ = parseaddr(sender)
                                if display_name:
                                    # Clean up common suffixes
                                    cleaned = re.sub(
                                        r"\s*(Talent|Careers?|Jobs?|Recruiting|HR|Notifications?|Team|Hiring|Acquisition)\s*$",
                                        "",
                                        display_name,
                                        flags=re.IGNORECASE,
                                    ).strip()
                                    if cleaned and len(cleaned) > 2:
                                        company_name = cleaned
                                        break

                        # Final fallback: use the main domain name (not subdomain)
                        if not company_name:
                            parts = domain.split(".")
                            if len(parts) >= 2:
                                # Use the second-to-last part (e.g., "brassring" from "trm.brassring.com")
                                company_name = parts[-2].title()
                            else:
                                company_name = parts[0].title()

                        domain_to_company[domain] = company_name

                    # Save to JSON files
                    personal_domains_data["domains"] = sorted(personal_domains)
                    with open(personal_domains_path, "w", encoding="utf-8") as f:
                        json.dump(
                            personal_domains_data, f, indent=2, ensure_ascii=False
                        )

                    companies_data["domain_to_company"] = dict(
                        sorted(domain_to_company.items())
                    )
                    companies_data["ats_domains"] = sorted(ats_domains)
                    companies_data["headhunter_domains"] = sorted(headhunter_domains)
                    companies_data["job_boards"] = sorted(job_boards)
                    with open(companies_path, "w", encoding="utf-8") as f:
                        json.dump(companies_data, f, indent=2, ensure_ascii=False)

                    messages.success(request, f"✅ Labeled {domain} as {label_type}.")
                    return redirect(
                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                    )
                except Exception as e:
                    messages.error(request, f"⚠️ Error saving domain label: {e}")
                    logger.exception("Error in label_single")
                    return redirect(
                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                    )

    # Reload JSON data to ensure we have the latest classifications
    # (Important after POST operations that modify the files)
    if companies_path.exists():
        with open(companies_path, "r", encoding="utf-8") as f:
            companies_data = json.load(f)
    if personal_domains_path.exists():
        with open(personal_domains_path, "r", encoding="utf-8") as f:
            personal_domains_data = json.load(f)

    domain_to_company = companies_data.get("domain_to_company", {})
    ats_domains = set(companies_data.get("ats_domains", []))
    headhunter_domains = set(companies_data.get("headhunter_domains", []))
    job_boards = set(companies_data.get("job_boards", []))
    personal_domains = set(personal_domains_data.get("domains", []))

    # Extract all sender domains from messages
    messages_qs = Message.objects.all()
    domain_counter = Counter()
    domain_senders = defaultdict(list)

    for msg in messages_qs.values("sender"):
        sender = msg["sender"]
        if "@" in sender:
            # Parse email from "Name <email@domain.com>" or "email@domain.com"
            email = sender
            if "<" in sender and ">" in sender:
                # Find the last <...> that contains an @ symbol
                import re

                email_matches = re.findall(r"<([^>]+@[^>]+)>", sender)
                if email_matches:
                    email = email_matches[-1]  # Use the last match
                else:
                    # Fallback to original logic if regex fails
                    email = sender[sender.rindex("<") + 1 : sender.rindex(">")]

            # Only process if email contains @
            if "@" in email:
                domain = email.split("@")[-1].lower()

                # Skip placeholder domains from manual entries
                if domain == "manual" or domain.startswith("manual_"):
                    continue

                domain_counter[domain] += 1

                # Store sample senders (limit to 3)
                if len(domain_senders[domain]) < 3:
                    domain_senders[domain].append(sender[:50])

    # Build domain info list
    domains_info = []
    for domain, count in domain_counter.items():
        # Determine current label
        label = None
        company_name = None

        if domain in personal_domains:
            label = "personal"
        elif domain in ats_domains:
            label = "ats"
        elif domain in headhunter_domains:
            label = "headhunter"
        elif domain in job_boards:
            label = "job_boards"
        elif domain in domain_to_company:
            label = "company"
            company_name = domain_to_company[domain]

        domains_info.append(
            {
                "domain": domain,
                "count": count,
                "label": label,
                "company_name": company_name,
                "sample_senders": domain_senders[domain],
            }
        )

    # Filter based on query parameter
    current_filter = request.GET.get("filter", "unlabeled")
    search_query = request.GET.get("search", "").strip().lower()
    sort_by = request.GET.get("sort", "domain")  # domain, count, label
    sort_order = request.GET.get("order", "asc")  # asc, desc

    # Apply search filter
    if search_query:
        domains_info = [d for d in domains_info if search_query in d["domain"].lower()]

    # Apply category filter
    if current_filter == "unlabeled":
        domains_info = [d for d in domains_info if d["label"] is None]
    elif current_filter == "personal":
        domains_info = [d for d in domains_info if d["label"] == "personal"]
    elif current_filter == "company":
        domains_info = [d for d in domains_info if d["label"] == "company"]
    elif current_filter == "ats":
        domains_info = [d for d in domains_info if d["label"] == "ats"]
    elif current_filter == "headhunter":
        domains_info = [d for d in domains_info if d["label"] == "headhunter"]
    elif current_filter == "job_boards":
        # Option A: Use job_boards from JSON as canonical source
        jb_set = set(job_boards)
        # Augment existing info with any missing job board domains (ensure visibility even if no messages yet)
        existing_domains = {d["domain"] for d in domains_info}
        for jb in jb_set:
            if jb not in existing_domains:
                domains_info.append(
                    {
                        "domain": jb,
                        "count": 0,
                        "label": "job_boards",
                        "company_name": None,
                        "sample_senders": [],
                    }
                )
        # Filter to job boards
        domains_info = [d for d in domains_info if d["label"] == "job_boards"]
    # "all" shows everything

    # Apply sorting
    if sort_by == "count":
        domains_info.sort(key=lambda d: d["count"], reverse=(sort_order == "desc"))
    elif sort_by == "label":

        def label_sort_key(d):
            label = d["label"] or "zzz_unlabeled"  # Push unlabeled to end
            return label

        domains_info.sort(key=label_sort_key, reverse=(sort_order == "desc"))
    else:  # sort_by == "domain" (default)
        # Sort alphabetically by full domain name
        domains_info.sort(
            key=lambda d: d["domain"].lower(), reverse=(sort_order == "desc")
        )

    # Calculate stats; align Job Boards badge to JSON canonical list
    all_domains = list(domain_counter.keys())
    stats = {
        "total": len(all_domains),
        "unlabeled": sum(
            1
            for d in all_domains
            if d not in personal_domains
            and d not in ats_domains
            and d not in headhunter_domains
            and d not in job_boards
            and d not in domain_to_company
        ),
        "personal": len(personal_domains),
        "company": len(domain_to_company),
        "ats": len(ats_domains),
        "headhunter": len(headhunter_domains),
        "job_boards": len(set(job_boards)),
    }

    ctx = {
        "domains": domains_info,
        "current_filter": current_filter,
        "stats": stats,
        "reingest_summary": reingest_summary,
        "search_query": search_query,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    # Include debug counts
    ctx["debug_counts"] = debug_counts
    return render(request, "tracker/manage_domains.html", ctx)


__all__ = ["delete_company", "label_companies", "merge_companies", "manage_domains"]
