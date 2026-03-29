import json
import shutil
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from tracker.models import Company, Message, ThreadTracking


@contextmanager
def temporary_domain_config():
    """Swap writable temp copies of the domain config files into place for a test."""
    original_paths = [
        Path("json/companies.json"),
        Path("json/personal_domains.json"),
    ]
    backups = []

    try:
        for original_path in original_paths:
            backup_path = original_path.with_suffix(f"{original_path.suffix}.baktest")
            temp_live_path = original_path.with_suffix(f"{original_path.suffix}.testtmp")

            shutil.copy(original_path, temp_live_path)
            original_path.rename(backup_path)
            temp_live_path.rename(original_path)
            backups.append((original_path, backup_path))

        yield
    finally:
        for original_path, backup_path in backups:
            original_path.unlink(missing_ok=True)
            backup_path.rename(original_path)


@pytest.mark.django_db
def test_preview_personal_cleanup_requires_confirmation_for_job_related_messages(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="manage-domains-user",
        password="password",
    )
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Preview Corp",
        domain="preview.example",
        first_contact=now,
        last_contact=now,
    )
    Message.objects.create(
        msg_id="preview-msg-1",
        thread_id="preview-thread-1",
        subject="Application received",
        sender="jobs@preview.example",
        timestamp=now,
        company=company,
        ml_label="job_application",
        confidence=0.99,
        reviewed=True,
        body="body",
    )

    response = client.post(
        reverse("preview_personal_domain_cleanup"),
        data=json.dumps({"domains": ["preview.example"]}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert payload["non_noise_messages"] == 1
    assert payload["company_names"] == ["Preview Corp"]


@pytest.mark.django_db
def test_manage_domains_personal_label_without_confirmation_keeps_company(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="manage-domains-guard-user",
        password="password",
    )
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Guard Corp",
        domain="guard.example",
        first_contact=now,
        last_contact=now,
    )
    Message.objects.create(
        msg_id="guard-msg-1",
        thread_id="guard-thread-1",
        subject="Interview scheduled",
        sender="jobs@guard.example",
        timestamp=now,
        company=company,
        ml_label="interview_invite",
        confidence=0.99,
        reviewed=True,
        body="body",
    )

    with temporary_domain_config():
        response = client.post(
            reverse("manage_domains"),
            data={
                "action": "label_single",
                "domain": "guard.example",
                "label_type": "personal",
            },
        )

    assert response.status_code == 302
    assert Company.objects.filter(id=company.id).exists()
    assert Message.objects.filter(company=company).count() == 1


@pytest.mark.django_db
def test_manage_domains_personal_label_deletes_noise_only_company(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="manage-domains-delete-user",
        password="password",
    )
    client.force_login(user)

    now = timezone.now()
    company = Company.objects.create(
        name="Noise Corp",
        domain="noise.example",
        first_contact=now,
        last_contact=now,
    )
    Message.objects.create(
        msg_id="noise-msg-1",
        thread_id="noise-thread-1",
        subject="Automated notification",
        sender="alerts@noise.example",
        timestamp=now,
        company=company,
        ml_label="noise",
        confidence=1.0,
        reviewed=True,
        body="body",
    )
    ThreadTracking.objects.create(
        thread_id="noise-thread-1",
        company=company,
        company_source="domain_mapping",
        job_title="Noise Job",
        status="application",
        sent_date=now.date(),
        ml_label="noise",
        reviewed=True,
    )

    with temporary_domain_config():
        response = client.post(
            reverse("manage_domains"),
            data={
                "action": "label_single",
                "domain": "noise.example",
                "label_type": "personal",
            },
            follow=True,
        )
        personal_domains = json.loads(
            Path("json/personal_domains.json").read_text(encoding="utf-8")
        )

    assert response.status_code == 200
    assert "noise.example" in personal_domains["domains"]
    assert not Company.objects.filter(id=company.id).exists()
    assert not ThreadTracking.objects.filter(thread_id="noise-thread-1").exists()


@pytest.mark.django_db
def test_manage_domains_shows_latest_detected_domains(
    client,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="manage-domains-latest-user",
        password="password",
    )
    client.force_login(user)

    now = timezone.now()
    older = now - timedelta(days=2)
    newer = now - timedelta(hours=1)

    Message.objects.create(
        msg_id="old-domain-msg",
        thread_id="old-domain-thread",
        subject="Old domain",
        sender="jobs@old.example",
        timestamp=older,
        ml_label="noise",
        confidence=1.0,
        reviewed=True,
        body="body",
    )
    Message.objects.create(
        msg_id="new-domain-msg",
        thread_id="new-domain-thread",
        subject="New domain",
        sender="jobs@new.example",
        timestamp=newer,
        ml_label="noise",
        confidence=1.0,
        reviewed=True,
        body="body",
    )

    response = client.get(reverse("manage_domains"))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Latest Domains Detected" in body
    assert body.index("new.example") < body.index("old.example")