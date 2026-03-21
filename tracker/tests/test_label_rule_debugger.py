from pathlib import Path

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_label_rule_debugger_shows_rule_trace_sections(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="debugger-user", password="password"
    )
    client.force_login(user)

    fixture_path = Path(__file__).resolve().parents[2] / "tests" / "emails" / (
        "Equal Opportunity Compliance Form Request with PSI Pax - "
        "Senior Systems Security Engineer (_2937) Opportunity.eml"
    )
    raw_message = fixture_path.read_text(encoding="utf-8", errors="replace")

    response = client.post(
        reverse("label_rule_debugger"),
        {"pasted_message": raw_message},
    )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Final Classification Source:" in body
    assert "Show raw matched patterns" in body
    assert "Show excluded or skipped pattern matches" in body
    assert "Show chronological decision trace" in body
    assert "ML" in body
    assert "skipped by domain safeguard" in body
    assert "ATS domain" in body
    assert "head_hunter" in body
    assert "special_indeed_subject" in body
    assert "priority_other" in body