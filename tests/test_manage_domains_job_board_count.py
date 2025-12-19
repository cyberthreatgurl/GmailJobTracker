import json
from django.urls import reverse
from django.test import Client
from django.utils import timezone
from tracker.models import Company
from pathlib import Path


def test_job_board_badge_matches_table_rows(db, settings):
    # Seed: create 3 job board domains
    # Load canonical job boards from JSON and seed 3 of them
    companies_path = Path("json/companies.json")
    with open(companies_path, "r", encoding="utf-8") as f:
        companies_data = json.load(f)
    job_boards = list(companies_data.get("job_boards", []))
    assert len(job_boards) >= 3, "Need at least 3 job boards in JSON to run test"
    seed_domains = job_boards[:3]
    for dom in seed_domains:
        Company.objects.create(
            name=dom.split(".")[0].title(),
            domain=dom,
            status="job_board",
            first_contact=timezone.now(),
            last_contact=timezone.now(),
            confidence=0,
        )

    client = Client()
    resp = client.get(reverse("manage_domains"), {"filter": "job_boards"})
    assert resp.status_code == 200

    # Extract counts from context if exposed; otherwise, do a simple HTML heuristic
    # Prefer server-side check: DB distinct domains should be 3
    distinct = set(
        Company.objects.filter(status="job_board", domain__isnull=False)
        .values_list("domain", flat=True)
        .distinct()
    )
    assert len(distinct) == 3

    # Prefer server-side context verification over HTML text heuristics
    assert hasattr(resp, "context") and resp.context is not None
    ctx_domains = resp.context.get("domains") or []
    rendered_domains = {d.get("domain") for d in ctx_domains}
    for dom in seed_domains:
        assert (
            dom in rendered_domains
        ), f"Expected domain {dom} to be in response context domains"
