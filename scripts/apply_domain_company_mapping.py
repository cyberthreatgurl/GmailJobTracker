import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

import json
from tracker.models import Message, ThreadTracking, Company

EML_THREAD_ID = "19aa1ce0506cf65b"


def load_domain_map():
    cfg_path = ROOT / "json" / "companies.json"
    if not cfg_path.exists():
        return {}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return cfg.get("domain_to_company", {})


import re


def domain_from_address(addr: str):
    if not addr:
        return None
    m = re.search(r"@([\w\.-]+)", addr)
    return m.group(1).lower() if m else None


def main():
    domain_map = load_domain_map()
    tt = ThreadTracking.objects.filter(thread_id=EML_THREAD_ID).first()
    if not tt:
        print("No ThreadTracking found for", EML_THREAD_ID)
        return
    # find a representative message in the thread
    msg = Message.objects.filter(thread_id=EML_THREAD_ID).order_by("-timestamp").first()
    if not msg:
        print("No Message found for", EML_THREAD_ID)
        return

    sender = msg.sender or ""
    domain = domain_from_address(sender)
    mapped = domain_map.get(domain)
    if not mapped:
        print("No mapping for domain", domain)
        return

    company_obj, created = Company.objects.get_or_create(
        name=mapped,
        defaults={
            "domain": domain or "",
            "first_contact": msg.timestamp or None,
            "last_contact": msg.timestamp or None,
        },
    )
    # assign to message and thread
    msg.company = company_obj
    msg.company_source = "domain_mapping"
    msg.save()

    tt.company = company_obj
    tt.save()

    print(
        "Assigned company",
        company_obj.name,
        "to Message id=",
        msg.id,
        "ThreadTracking id=",
        tt.id,
    )


if __name__ == "__main__":
    main()
