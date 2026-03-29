from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from tracker.models import AuditEvent, Company, CompanyDocument, Message, ThreadTracking


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
    assert body.count("company-metrics-action") >= 5
    assert body.count("btn-secondary company-metrics-action") >= 5


@pytest.mark.django_db
def test_label_companies_shows_visible_homepage_input_for_selected_company(
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
    assert '<label for="id_homepage">Homepage</label>' in body
    assert 'name="homepage"' in body
    assert 'value="http://www.pure.net"' in body
    assert '<label for="id_domain">Domain Name</label>' not in body


@pytest.mark.django_db
def test_label_companies_renders_uploaded_document_count_without_raw_template_text(
    client,
    django_user_model,
    settings,
    tmp_path,
):
    settings.MEDIA_ROOT = tmp_path
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]

    user = django_user_model.objects.create_user(username="document-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Obsidian",
        domain="obsidian.example",
        first_contact=now,
        last_contact=now,
    )
    CompanyDocument.objects.create(
        company=company,
        file=SimpleUploadedFile("offer.txt", b"offer details", content_type="text/plain"),
        description="Offer letter",
    )

    response = client.get(f"/label_companies/?company={company.id}", HTTP_HOST="localhost")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Documents (1)" in body
    assert "{{ company_documents|length }}" not in body
    assert "offer.txt" in body


@pytest.mark.django_db
def test_label_companies_shows_exact_assigned_reingest_count(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(username="reingest-count-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Red River",
        domain="redriver.com",
        first_contact=now,
        last_contact=now,
    )
    other_company = Company.objects.create(
        name="OtherCo",
        domain="redriver.com",
        first_contact=now,
        last_contact=now,
    )

    Message.objects.create(
        msg_id="msg-assigned-1",
        thread_id="thread-1",
        subject="Assigned 1",
        sender="jobs@redriver.com",
        timestamp=now,
        company=company,
        ml_label="job_application",
        confidence=0.9,
        reviewed=True,
    )
    Message.objects.create(
        msg_id="msg-assigned-2",
        thread_id="thread-2",
        subject="Assigned 2",
        sender="jobs@redriver.com",
        timestamp=now,
        company=company,
        ml_label="other",
        confidence=0.9,
        reviewed=True,
    )
    Message.objects.create(
        msg_id="msg-same-domain-other-company",
        thread_id="thread-3",
        subject="Other company",
        sender="jobs@redriver.com",
        timestamp=now,
        company=other_company,
        ml_label="job_application",
        confidence=0.9,
        reviewed=True,
    )

    response = client.get(f"/label_companies/?company={company.id}")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Re-ingest 2 Assigned Messages" in body
    assert "Re-ingest exactly 2 messages explicitly assigned to this company" in body
    assert "Preview Included Messages" in body
    assert "This preview uses the exact assigned-message set that will be re-ingested." in body
    assert "Assigned 1" in body
    assert "Assigned 2" in body
    assert "Other company" not in body


@pytest.mark.django_db
def test_label_companies_renders_cancelled_application_without_template_artifacts(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(username="cancelled-app-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Software Engineering Institute",
        domain="sei.cmu.edu",
        first_contact=now,
        last_contact=now,
    )

    ThreadTracking.objects.create(
        thread_id="thread-cancelled",
        company=company,
        job_title="application",
        ml_label="job_application",
        status="application",
        sent_date=now.date(),
        rejection_date=now.date(),
        cancelled=True,
        reviewed=True,
    )
    ThreadTracking.objects.create(
        thread_id="thread-rejected",
        company=company,
        job_title="Senior AI Security Engineer",
        ml_label="rejection",
        status="rejected",
        sent_date=now.date(),
        rejection_date=now.date(),
        reviewed=True,
    )
    Message.objects.create(
        msg_id="msg-cancelled",
        thread_id="thread-cancelled",
        subject="Application received",
        sender="jobs@sei.cmu.edu",
        timestamp=now,
        company=company,
        ml_label="job_application",
        confidence=0.9,
        reviewed=True,
    )
    Message.objects.create(
        msg_id="msg-rejected",
        thread_id="thread-rejected",
        subject="Application received",
        sender="jobs@sei.cmu.edu",
        timestamp=now,
        company=company,
        ml_label="job_application",
        confidence=0.9,
        reviewed=True,
    )

    response = client.get(f"/label_companies/?company={company.id}")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "CANCELLED" in body
    assert "Senior AI Security Engineer" in body
    assert "{% elif" not in body
    assert "thread.withdrew" not in body
    
@patch("gmail_auth.get_gmail_service", return_value=object())
def test_label_companies_reingest_company_only_reingests_assigned_messages_and_clears_reviewed_after_success(
    _mock_service,
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(username="reingest-user", password="password")
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Red River",
        domain="redriver.com",
        first_contact=now,
        last_contact=now,
    )
    other_company = Company.objects.create(
        name="OtherCo",
        domain="redriver.com",
        first_contact=now,
        last_contact=now,
    )

    success_msg = Message.objects.create(
        msg_id="msg-success",
        thread_id="thread-success",
        subject="Assigned success",
        sender="jobs@redriver.com",
        timestamp=now,
        company=company,
        ml_label="job_application",
        confidence=0.9,
        reviewed=True,
    )
    failed_msg = Message.objects.create(
        msg_id="msg-fail",
        thread_id="thread-fail",
        subject="Assigned fail",
        sender="jobs@redriver.com",
        timestamp=now,
        company=company,
        ml_label="other",
        confidence=0.9,
        reviewed=True,
    )
    untouched_msg = Message.objects.create(
        msg_id="msg-other-company",
        thread_id="thread-other",
        subject="Same domain different company",
        sender="jobs@redriver.com",
        timestamp=now,
        company=other_company,
        ml_label="job_application",
        confidence=0.9,
        reviewed=True,
    )

    success_tt = ThreadTracking.objects.create(
        thread_id="thread-success",
        company=company,
        reviewed=True,
        sent_date=now.date(),
        status="applied",
    )
    failed_tt = ThreadTracking.objects.create(
        thread_id="thread-fail",
        company=company,
        reviewed=True,
        sent_date=now.date(),
        status="applied",
    )
    untouched_tt = ThreadTracking.objects.create(
        thread_id="thread-other",
        company=other_company,
        reviewed=True,
        sent_date=now.date(),
        status="applied",
    )

    ingest_calls = []

    def fake_ingest_message(_service, msg_id):
        ingest_calls.append(msg_id)
        if msg_id == "msg-fail":
            raise RuntimeError("boom")

    parser_module = SimpleNamespace(ingest_message=fake_ingest_message)

    with patch("tracker.views.companies._get_parser_module", return_value=parser_module):
        response = client.post(
            f"/label_companies/?company={company.id}",
            {"company": str(company.id), "action": "reingest_company"},
        )

    assert response.status_code == 302
    assert set(ingest_calls) == {"msg-success", "msg-fail"}
    assert "msg-other-company" not in ingest_calls

    success_msg.refresh_from_db()
    failed_msg.refresh_from_db()
    untouched_msg.refresh_from_db()
    success_tt.refresh_from_db()
    failed_tt.refresh_from_db()
    untouched_tt.refresh_from_db()

    assert success_msg.reviewed is False
    assert success_tt.reviewed is False
    assert failed_msg.reviewed is True
    assert failed_tt.reviewed is True
    assert untouched_msg.reviewed is True
    assert untouched_tt.reviewed is True

    assert AuditEvent.objects.filter(
        action="ui_reingest_clear",
        source="reingest_company",
        msg_id="msg-success",
    ).count() == 1
    assert AuditEvent.objects.filter(
        action="ui_reingest_clear",
        source="reingest_company",
        msg_id="msg-fail",
    ).count() == 0


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