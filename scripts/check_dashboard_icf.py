import os, sys, json
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from tracker.models import Company, ThreadTracking, Message
from django.db.models import Q
from datetime import datetime


def load_headhunter_domains():
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
    return headhunter_domains


def main():
    cid = 134
    comp = Company.objects.filter(id=cid).first()
    print("Company:", cid, comp.name if comp else None)

    headhunter_domains = load_headhunter_domains()
    print("headhunter_domains:", headhunter_domains[:5])

    # build hh_company_list
    hh_company_list = []
    if headhunter_domains:
        hh_company_q = Q()
        for d in headhunter_domains:
            hh_company_q |= Q(domain__iendswith=d)
        msg_hh_q = Q()
        for d in headhunter_domains:
            msg_hh_q |= Q(message__sender__icontains=f"@{d}")
        hh_companies = (
            Company.objects.filter(
                hh_company_q | msg_hh_q | Q(message__ml_label="head_hunter")
            )
            .distinct()
            .values_list("id", flat=True)
        )
        hh_company_list = list(hh_companies)
    print("hh_company_list sample:", hh_company_list[:10])

    # Build tracked_thread_companies
    tt_with_interview = ThreadTracking.objects.filter(
        interview_date__isnull=False, company__isnull=False
    ).values("thread_id", "company_id")
    tracked = {(item["thread_id"], item["company_id"]) for item in tt_with_interview}
    print("tracked thread-company pairs count:", len(tracked))

    # msg interview qs
    msg_interviews_qs = Message.objects.filter(
        ml_label__in=["interview_invite", "interview"], company__isnull=False
    ).select_related("company")
    # apply headhunter filters
    if headhunter_domains:
        for d in headhunter_domains:
            msg_interviews_qs = msg_interviews_qs.exclude(sender__icontains=f"@{d}")
    if hh_company_list:
        msg_interviews_qs = msg_interviews_qs.exclude(company_id__in=hh_company_list)

    # list matching messages
    msgs = list(msg_interviews_qs.order_by("timestamp"))
    print("Total interview-labeled messages (after filters):", len(msgs))
    for m in msgs:
        print(
            "MSG",
            m.id,
            m.thread_id,
            m.company_id,
            m.company.name if m.company else None,
            m.ml_label,
            m.timestamp,
        )

    present = any(m.company_id == cid for m in msgs)
    print("ICF present in interview messages after filtering?", present)


if __name__ == "__main__":
    main()
