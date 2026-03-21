from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from tracker.models import Company


@pytest.mark.django_db
def test_label_companies_renders_contract_refresh_targets(client, django_user_model):
    user = django_user_model.objects.create_user(username="contracts-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Acme Corp",
        domain="acme.example",
        first_contact=now,
        last_contact=now,
    )

    response = client.get(f"/label_companies/?company={company.id}")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'id="refresh-contracts-btn"' in body
    assert 'id="company-contracts-summary"' in body
    assert 'id="company-contracts-section"' in body


@pytest.mark.django_db
def test_label_companies_shows_homepage_domain_without_visible_input(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(username="homepage-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Pure",
        domain="pure.net",
        homepage="http://www.pure.net",
        first_contact=now,
        last_contact=now,
    )

    response = client.get(f"/label_companies/?company={company.id}")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Domain:" in body
    assert "pure.net" in body
    assert '<label for="id_homepage">Homepage</label>' not in body
    assert '<label for="id_domain">Domain Name</label>' not in body


@pytest.mark.django_db
def test_existing_company_save_syncs_domain_from_homepage(client, django_user_model):
    user = django_user_model.objects.create_user(username="sync-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Cisco",
        domain="old.example",
        homepage="https://www.cisco.com",
        first_contact=now,
        last_contact=now,
    )

    response = client.post(
        f"/label_companies/?company={company.id}",
        {
            "company": str(company.id),
            "name": company.name,
            "location": "",
            "domain": "manual.example",
            "ats": "",
            "homepage": "https://www.cisco.com",
            "contact_name": "",
            "contact_email": "",
            "uei": "",
            "duns_number": "",
            "status": company.status or "application",
            "notes": "",
            "focus_area": "",
            "career_url": "",
            "alias": "",
            "operating_cities_text": "",
        },
    )

    assert response.status_code == 302
    company.refresh_from_db()
    assert company.domain == "cisco.com"


@pytest.mark.django_db
def test_new_company_create_syncs_domain_from_homepage(client, django_user_model):
    user = django_user_model.objects.create_user(username="new-sync-user", password="password")
    client.force_login(user)

    response = client.post(
        "/label_companies/?company=new&new_company_name=Pure",
        {
            "action": "create_new_company",
            "name": "Pure",
            "location": "",
            "domain": "manual.example",
            "ats": "",
            "homepage": "http://www.pure.net",
            "contact_name": "",
            "contact_email": "",
            "uei": "",
            "duns_number": "",
            "status": "new",
            "notes": "",
            "focus_area": "",
            "career_url": "",
            "alias": "",
            "operating_cities_text": "",
        },
    )

    assert response.status_code == 302
    company = Company.objects.get(name="Pure")
    assert company.domain == "pure.net"


@pytest.mark.django_db
@patch("tracker.views.companies.USASpendingService")
def test_refresh_company_contracts_endpoint_returns_success(
    mock_service_class,
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(username="contracts-api-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Acme Corp",
        domain="acme.example",
        first_contact=now,
        last_contact=now,
    )

    mock_service_class.return_value.fetch_contracts_for_company.return_value = {
        "created": 2,
        "updated": 1,
        "errors": 0,
    }

    response = client.post(reverse("refresh_company_contracts", args=[company.id]))

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Fetched 2 new, 1 updated contracts.",
        "data": {"created": 2, "updated": 1, "errors": 0},
    }