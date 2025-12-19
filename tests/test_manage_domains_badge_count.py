import json
from pathlib import Path
from django.test import Client
from django.urls import reverse


def test_job_boards_badge_matches_json_count(db, settings):
    """Ensure the Job Boards badge equals the JSON canonical count."""
    companies_path = Path("json/companies.json")
    with open(companies_path, "r", encoding="utf-8") as f:
        companies_data = json.load(f)
    job_boards = set(companies_data.get("job_boards", []))

    client = Client()
    resp = client.get(reverse("manage_domains"))
    assert resp.status_code == 200

    assert hasattr(resp, "context") and resp.context is not None
    stats = resp.context.get("stats") or {}
    assert stats.get("job_boards") == len(job_boards)
