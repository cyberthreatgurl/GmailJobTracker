import json
from collections import defaultdict
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from tracker.models import Message


@login_required
def manage_domains(request):
    """
    Domain management page for classifying email domains as personal, company, ATS, or headhunter.
    Extracts domains from ingested messages and allows bulk labeling.
    """
    from collections import Counter
    from db import COMPANIES_PATH

    # Paths to JSON files
    companies_path = Path(__file__).parent.parent / "json" / "companies.json"
    personal_domains_path = (
        Path(__file__).parent.parent / "json" / "personal_domains.json"
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
    personal_domains = set(personal_domains_data.get("domains", []))

    # Handle POST requests for labeling
    if request.method == "POST":
        action = request.POST.get("action")
        label_type = request.POST.get("label_type")

        if action == "bulk_label":
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
                        if domain in domain_to_company:
                            del domain_to_company[domain]

                    # Add to selected category
                    if label_type == "personal":
                        personal_domains.update(domains)
                    elif label_type == "ats":
                        ats_domains.update(domains)
                    elif label_type == "headhunter":
                        headhunter_domains.update(domains)
                    elif label_type == "company":
                        # For company, we need to prompt for company name
                        # For now, just add to domain_to_company with domain as placeholder
                        for domain in domains:
                            if domain not in domain_to_company:
                                # Try to infer company name from domain
                                company_name = domain.split(".")[0].title()
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
                    if domain in domain_to_company:
                        del domain_to_company[domain]

                    # Add to selected category
                    if label_type == "personal":
                        personal_domains.add(domain)
                    elif label_type == "ats":
                        ats_domains.add(domain)
                    elif label_type == "headhunter":
                        headhunter_domains.add(domain)
                    elif label_type == "company":
                        company_name = domain.split(".")[0].title()
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

                    messages.success(request, f"✅ Labeled {domain} as {label_type}.")
                    return redirect(
                        f"{request.path}?filter={request.GET.get('filter', 'unlabeled')}"
                    )
                except Exception as e:
                    messages.error(request, f"⚠️ Error saving domain label: {e}")

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
                email = sender[sender.index("<") + 1 : sender.index(">")]

            domain = email.split("@")[-1].lower()
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

    # Sort by count (descending)
    domains_info.sort(key=lambda x: x["count"], reverse=True)

    # Filter based on query parameter
    current_filter = request.GET.get("filter", "unlabeled")
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
    # "all" shows everything

    # Calculate stats
    all_domains = list(domain_counter.keys())
    stats = {
        "total": len(all_domains),
        "unlabeled": sum(
            1
            for d in all_domains
            if d not in personal_domains
            and d not in ats_domains
            and d not in headhunter_domains
            and d not in domain_to_company
        ),
        "personal": len(personal_domains),
        "company": len(domain_to_company),
        "ats": len(ats_domains),
        "headhunter": len(headhunter_domains),
    }

    ctx = {
        "domains": domains_info,
        "current_filter": current_filter,
        "stats": stats,
    }
    return render(request, "tracker/manage_domains.html", ctx)
