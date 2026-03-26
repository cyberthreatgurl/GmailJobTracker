# test_ingest_message.py
# pylint: disable=redefined-outer-name

from datetime import datetime
from parser import ingest_message, _update_existing_thread_tracking, _update_thread_tracking_for_company  # pylint: disable=deprecated-module

import pytest
from django.utils.timezone import make_aware

from tracker.models import Company, Message, ThreadTracking
from tracker.tests.test_helpers import FakeMessageRecord

pytestmark = pytest.mark.django_db
timestamp = make_aware(datetime(2025, 9, 29, 12, 0))


def test_ingest_ignored_reason_logging(monkeypatch, fake_stats, fake_message_model):
    _, _ = fake_message_model
    captured = {}

    # Patch log_ignored_message to capture its arguments
    monkeypatch.setattr(
        "parser.log_ignored_message",
        lambda msg_id, metadata, reason: captured.update(
            {
                "msg_id": msg_id,
                "reason": reason,
                "subject": metadata["subject"],
                "sender": metadata["sender"],
            }
        ),
    )

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "foo",
            "body": "bar",
            "date": "2025-09-29",
            "thread_id": "t8",
            "sender": "x",
            "sender_domain": "example.com",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )

    # Parsed subject flags the message as ignored
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": True,
            "ignore_reason": "ml_ignore",
            "company": "",
            "job_title": "",
            "job_id": "",
        },
    )

    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m8")
    assert result == {"status": "ignored", "reason": "ml_ignore"}
    assert fake_stats.total_ignored == 1

    # ✅ Confirm log_ignored_message was called with correct values
    assert captured["msg_id"] == "m8"
    assert captured["reason"] == "ml_ignore"
    assert captured["subject"] == "foo"
    assert captured["sender"] == "x"


@pytest.fixture
def fake_stats():
    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0
        # Added date attribute used by IngestionStats update logic
        date = "2025-09-29"

        def save(self):
            pass

    return Stats()


def test_ingest_ignored(monkeypatch, fake_stats, fake_message_model):
    _, _ = fake_message_model
    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "foo",
            "body": "bar",
            "date": "2025-09-29",
            "thread_id": "t1",
            "sender": "x",
            "sender_domain": "y",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )
    monkeypatch.setattr("parser.classify_message", lambda b: None)
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {"ignore": True})
    monkeypatch.setattr("parser.log_ignored_message", lambda *a, **k: None)
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m1")
    assert result == {"status": "ignored", "reason": "ml_ignore"}
    assert fake_stats.total_ignored == 1


def test_ingest_skipped(monkeypatch, fake_stats, fake_message_model):
    timestamp = make_aware(datetime(2025, 9, 29, 12, 0))

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "foo",
            "body": "bar",
            "date": "2025-09-29",
            "thread_id": "t1",
            "sender": "x",
            "sender_domain": "y",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )

    monkeypatch.setattr("parser.classify_message", lambda b: {"label": "skipped"})
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {"ignore": False})
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    queryset, _ = fake_message_model
    queryset.set_first(FakeMessageRecord({"msg_id": "m2"}))

    result = ingest_message(None, "m2")
    assert result["status"] == "re-ingested"
    assert result["changed"] is True
    assert fake_stats.total_skipped == 1


def test_thank_you_message_does_not_set_interview_date(
    monkeypatch, fake_stats, fake_message_model
):
    """Regression test: a simple 'thank you for applying' message should not create an interview_date.

    This prevents false positives where automated acknowledgement/rejection emails are interpreted
    as scheduled interviews.
    """
    _, manager = fake_message_model

    # Simulate a typical 'thank you for applying' message
    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "Thank you for applying to ExampleCo",
            "body": "Thank you for your application. Our recruiting team will review your submission.",
            "date": "2025-10-01",
            "thread_id": "t_thanks",
            "sender": "ExampleCo Recruiting <no-reply@exampleco.com>",
            "sender_domain": "exampleco.com",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )

    # No status dates extracted from body
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )

    # Simulate ML subject classifier with low confidence (should not set interview_date)
    monkeypatch.setattr(
        "parser.predict_subject_type",
        lambda *a, **k: {"label": "job_application", "confidence": 0.25},
    )

    # Minimal subject parsing result to allow application creation
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "company": "ExampleCo",
            "job_title": "Engineer",
            "job_id": "",
            "predicted_company": "ExampleCo",
        },
    )

    monkeypatch.setattr("parser.classify_message", lambda b: None)
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m_thanks")
    assert result["status"] == "inserted"
    assert len(manager.created) == 1
    # Regression: ensure interview_date is not set from this acknowledgement message
    assert manager.created[0].get("interview_date") is None


def test_ingest_subject_parse(monkeypatch, fake_stats, fake_message_model):
    _, manager = fake_message_model

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "foo",
            "body": "bar",
            "date": "2025-09-29",
            "thread_id": "t1",
            "sender": "x",
            "sender_domain": "y",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )
    # Mock predict_subject_type to return job_application label with high confidence
    monkeypatch.setattr(
        "parser.predict_subject_type",
        lambda *a, **k: {"label": "job_application", "confidence": 0.95},
    )
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": False,
            "company": "TestCo",
            "job_title": "Engineer",
            "job_id": "123",
        },
    )
    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m3")
    assert result["status"] == "inserted"
    assert fake_stats.total_inserted == 1

    assert len(manager.created) == 1
    # ✅ Verify the inserted message content
    assert manager.created[0]["subject"] == "foo"
    assert manager.created[0]["thread_id"] == "t1"

    # ✅ Verify the final record
    assert manager.created[0]["company"].name == "TestCo"
    assert manager.created[0]["company_source"] == "subject_parse"
    assert manager.created[0]["subject"] == "foo"
    assert result["company"] == "TestCo"
    assert result["source"] == "subject_parse"


def test_ingest_ml_fallback(monkeypatch, fake_stats, fake_message_model):
    _, manager = fake_message_model

    # Patch ML prediction directly
    monkeypatch.setattr("parser.predict_company", lambda subject, body: "MLCo")
    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "Application for Software Engineer at MLCo",
            "body": "Thank you for applying to MLCo. We appreciate your interest.",
            "date": "2025-09-29",
            "thread_id": "t9",
            "sender": "x",
            "sender_domain": "unknown.com",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )

    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )

    # Mock predict_subject_type
    monkeypatch.setattr(
        "parser.predict_subject_type",
        lambda *a, **k: {"label": "job_application", "confidence": 0.95},
    )
    # Parsed subject returns no company
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": False,
            "company": "",
            "job_title": "Engineer",
            "job_id": "123",
        },
    )

    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m9")
    assert result["status"] == "inserted"
    assert fake_stats.total_inserted == 1

    # ✅ Confirm ML prediction was used
    assert len(manager.created) == 1
    assert manager.created[0]["company"].name == "MLCo"
    assert manager.created[0]["company_source"] == "ml_prediction"
    assert result["company"] == "MLCo"
    assert result["source"] == "ml_prediction"


def test_ingest_record_shape(monkeypatch, fake_stats, fake_message_model):
    _, manager = fake_message_model

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "foo",
            "body": "This is a job application email",
            "date": "2025-09-29",
            "thread_id": "t10",
            "sender": "x",
            "sender_domain": "example.com",
            "timestamp": timestamp,
            "labels": ["inbox", "jobs"],
            "last_updated": "now",
        },
    )

    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": "2025-09-30",
            "follow_up_dates": ["2025-10-02"],
            "rejection_date": None,
            "interview_date": "2025-10-05",
        },
    )

    # Mock predict_subject_type
    monkeypatch.setattr(
        "parser.predict_subject_type",
        lambda *a, **k: {"label": "job_application", "confidence": 0.95},
    )
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": False,
            "company": "TestCorp",
            "job_title": "Engineer",
            "job_id": "123",
            "predicted_company": "TestCorp",
        },
    )

    monkeypatch.setattr(
        "parser.build_company_job_index", lambda *a, **k: "testcorp_engineer_123"
    )
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m10")
    assert result["status"] == "inserted"
    assert fake_stats.total_inserted == 1
    assert len(manager.created) == 1

    # ✅ Verify full record schema (parser normalizes lists to comma-separated strings)
    assert manager.created[0]["subject"] == "foo"
    assert manager.created[0]["thread_id"] == "t10"
    assert manager.created[0]["company"].name == "TestCorp"
    assert manager.created[0]["company_source"] == "subject_parse"
    assert result["company"] == "TestCorp"
    assert result["source"] == "subject_parse"


def test_duplicate_application_ack_is_saved_as_other_but_updates_threadtracking(
    monkeypatch, fake_stats, fake_message_model
):
    """Duplicate acknowledgements should not persist as a second job_application message."""
    _, manager = fake_message_model
    captured = {}

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "Keep track of your application",
            "body": "Thank you for your interest in Senior Engineer (ID: J-12345).",
            "date": "2025-09-29",
            "thread_id": "t-dup",
            "sender": "noreply@mail.amazon.jobs",
            "sender_domain": "mail.amazon.jobs",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )
    monkeypatch.setattr(
        "parser.predict_subject_type",
        lambda *a, **k: {"label": "job_application", "confidence": 1.0},
    )
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": False,
            "company": "Amazon",
            "job_title": "Senior Engineer",
            "job_id": "J-12345",
            "predicted_company": "Amazon",
            "label": "job_application",
            "confidence": 1.0,
        },
    )
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)
    monkeypatch.setattr(
        "parser._is_duplicate_application_acknowledgement",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "parser._create_or_update_thread_tracking",
        lambda msg_id, metadata, result, *a, **k: captured.update(
            {
                "msg_id": msg_id,
                "thread_id": metadata["thread_id"],
                "label": result["label"],
            }
        ),
    )

    result = ingest_message(None, "m-dup")

    assert result["status"] == "inserted"
    assert len(manager.created) == 1
    assert manager.created[0]["ml_label"] == "other"
    assert captured["label"] == "job_application"


def test_prescreen_without_anchor_does_not_create_or_update_threadtracking():
    company = Company.objects.create(
        name="Amazon",
        domain="amazon.com",
        first_contact=timestamp,
        last_contact=timestamp,
    )
    existing_tt = ThreadTracking.objects.create(
        thread_id="tcurrentapp",
        company=company,
        company_source="subject_parse",
        job_title="Security Engineer",
        job_id="REQ-123",
        status="application",
        sent_date=timestamp.date(),
        ml_label="job_application",
        ml_confidence=0.99,
        reviewed=False,
    )

    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0

        def save(self):
            pass

    old_timestamp = make_aware(datetime(2024, 9, 29, 12, 0))
    metadata = {
        "thread_id": "toldprescreen",
        "timestamp": old_timestamp,
        "sender_domain": "amazon.com",
        "subject": "Phone screen availability",
        "body": "Are you available for a call next week?",
    }

    _update_thread_tracking_for_company(
        "m-old-prescreen",
        metadata,
        {"confidence": 0.95},
        company,
        "subject_parse",
        {"job_title": "", "job_id": ""},
        "application",
        False,
        Stats(),
        "prescreen",
        None,
        None,
        old_timestamp.date(),
    )

    existing_tt.refresh_from_db()
    assert existing_tt.prescreen_date is None
    assert ThreadTracking.objects.count() == 1


def test_prescreen_does_not_attach_to_future_application_even_with_matching_identity():
    company = Company.objects.create(
        name="Endyna",
        domain="endyna.com",
        first_contact=timestamp,
        last_contact=timestamp,
    )
    future_application = ThreadTracking.objects.create(
        thread_id="t-future-app",
        company=company,
        company_source="subject_parse",
        job_title="Cyber Security Project Manager",
        job_id="REQ-777",
        status="application",
        sent_date=datetime(2025, 11, 2).date(),
        ml_label="job_application",
        ml_confidence=0.99,
        reviewed=False,
    )

    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0

        def save(self):
            pass

    milestone_timestamp = make_aware(datetime(2025, 10, 24, 12, 0))
    metadata = {
        "thread_id": "t-prescreen-before-app",
        "timestamp": milestone_timestamp,
        "sender_domain": "endyna.com",
        "subject": "Cyber Security Project Manager phone screen",
        "body": "Let's schedule a phone screen for Cyber Security Project Manager (REQ-777).",
    }

    _update_thread_tracking_for_company(
        "m-future-prescreen",
        metadata,
        {"confidence": 0.95},
        company,
        "subject_parse",
        {"job_title": "Cyber Security Project Manager", "job_id": "REQ-777"},
        "application",
        False,
        Stats(),
        "prescreen",
        None,
        None,
        milestone_timestamp.date(),
    )

    future_application.refresh_from_db()
    assert future_application.prescreen_date is None
    assert ThreadTracking.objects.filter(company=company).count() == 1


def test_reingest_duplicate_reminder_thread_is_downgraded_without_recreating_application(
    monkeypatch,
):
    company = Company.objects.create(
        name="Amazon",
        domain="amazon.com",
        first_contact=timestamp,
        last_contact=timestamp,
    )
    ThreadTracking.objects.create(
        thread_id="19primaryapp",
        company=company,
        company_source="domain_mapping",
        job_title="Sr. Security Intelligence Engineer",
        job_id="3205410",
        status="application",
        sent_date=timestamp.date(),
        ml_label="job_application",
        ml_confidence=1.0,
        reviewed=False,
    )
    reminder_msg = Message.objects.create(
        msg_id="19reminderapp",
        thread_id="19reminderapp",
        subject="Keep track of your application",
        sender="noreply@mail.amazon.jobs",
        body="Thanks for applying to Amazon for the Sr. Security Intelligence Engineer (ID: 3205410) role.",
        timestamp=timestamp,
        company=company,
        company_source="domain_mapping",
        ml_label="job_application",
        confidence=1.0,
        reviewed=False,
    )
    reminder_tt = ThreadTracking.objects.create(
        thread_id="19reminderapp",
        company=company,
        company_source="domain_mapping",
        job_title="Sr. Security Intelligence Engineer , Threat Intelligence for Global Enterprise Response",
        job_id="3205410",
        status="application",
        sent_date=timestamp.date(),
        ml_label="job_application",
        ml_confidence=1.0,
        reviewed=False,
    )

    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0
        date = timestamp.date()

        def save(self):
            pass

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "Keep track of your application",
            "body": "Thanks for applying to Amazon for the Sr. Security Intelligence Engineer (ID: 3205410) role.",
            "body_html": "",
            "date": "2025-09-29",
            "thread_id": "19reminderapp",
            "sender": "noreply@mail.amazon.jobs",
            "sender_domain": "mail.amazon.jobs",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )
    monkeypatch.setattr(
        "parser.predict_subject_type",
        lambda *a, **k: {"label": "job_application", "confidence": 1.0},
    )
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": False,
            "company": "Amazon",
            "job_title": "Sr. Security Intelligence Engineer",
            "job_id": "3205410",
            "predicted_company": "Amazon",
            "label": "job_application",
            "confidence": 1.0,
        },
    )
    monkeypatch.setattr("parser.get_stats", lambda: Stats())

    result = ingest_message(None, "19reminderapp")

    assert result["status"] == "re-ingested"
    reminder_msg.refresh_from_db()
    reminder_tt.refresh_from_db()
    assert reminder_msg.ml_label == "other"
    assert reminder_tt.ml_label == "other"
    assert ThreadTracking.objects.filter(company=company).count() == 2


def test_reingest_noise_message_keeps_domain_mapped_company(monkeypatch):
    company = Company.objects.create(
        name="Idaho National Laboratory",
        domain="inl.gov",
        first_contact=timestamp,
        last_contact=timestamp,
    )
    existing = Message.objects.create(
        msg_id="19b14d7653cb21d0",
        thread_id="19b14d7653cb21d0",
        subject="Profile submitted to Idaho National Laboratory",
        sender="Idaho National Laboratory <staffing@inl.gov>",
        timestamp=timestamp,
        body=(
            "We have received the profile you submitted to our company. "
            "Please review our current job opportunities and apply online."
        ),
        ml_label="noise",
        confidence=1.0,
        reviewed=False,
    )

    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0
        date = timestamp.date()

        def save(self):
            pass

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m, raw_message=None: {
            "subject": "Profile submitted to Idaho National Laboratory",
            "body": (
                "We have received the profile you submitted to our company. "
                "Please review our current job opportunities and apply online."
            ),
            "date": "2025-12-12",
            "thread_id": "19b14d7653cb21d0",
            "sender": "Idaho National Laboratory <staffing@inl.gov>",
            "sender_domain": "inl.gov",
            "timestamp": timestamp,
            "labels": [],
            "last_updated": "now",
        },
    )
    monkeypatch.setattr("parser.classify_message", lambda b: "other")
    monkeypatch.setattr(
        "parser.extract_status_dates",
        lambda b, d: {
            "response_date": None,
            "follow_up_dates": [],
            "rejection_date": None,
            "interview_date": None,
        },
    )
    monkeypatch.setattr(
        "parser.predict_with_fallback",
        lambda *a, **k: {"label": "noise", "confidence": 1.0},
    )
    monkeypatch.setattr(
        "parser.parse_subject",
        lambda *a, **k: {
            "ignore": False,
            "company": "Idaho National Laboratory",
            "predicted_company": "Idaho National Laboratory",
            "job_title": "",
            "job_id": "",
            "label": "noise",
            "confidence": 1.0,
        },
    )
    monkeypatch.setattr("parser.get_stats", lambda: Stats())

    result = ingest_message(None, existing.msg_id)

    existing.refresh_from_db()
    assert result["status"] == "re-ingested"
    assert existing.ml_label == "noise"
    assert existing.company_id == company.id
    assert existing.company_source == "domain_mapping"


def test_offer_updates_associated_application_not_interview_thread():
    company = Company.objects.create(
        name="Endyna",
        domain="endyna.com",
        first_contact=timestamp,
        last_contact=timestamp,
    )
    application_tt = ThreadTracking.objects.create(
        thread_id="t-application",
        company=company,
        company_source="subject_parse",
        job_title="Cyber Security Project Manager",
        job_id="",
        status="application",
        sent_date=datetime(2025, 11, 2).date(),
        ml_label="job_application",
        ml_confidence=0.99,
        reviewed=False,
    )
    interview_tt = ThreadTracking.objects.create(
        thread_id="t-offer-thread",
        company=company,
        company_source="subject_parse",
        job_title="",
        job_id="",
        status="ghosted",
        sent_date=datetime(2025, 11, 7).date(),
        ml_label="interview_invite",
        ml_confidence=0.99,
        reviewed=False,
    )

    metadata = {
        "thread_id": "t-offer-thread",
        "timestamp": make_aware(datetime(2025, 11, 7, 12, 0)),
        "sender_domain": "endyna.com",
        "subject": "Let's Talk - EnDyna",
        "body": "Thank you for interviewing with our CEO about the Cyber Security Project Manager position.",
    }

    _update_existing_thread_tracking(
        metadata,
        {"confidence": 1.0},
        company,
        "subject_parse",
        {"job_title": "", "job_id": ""},
        None,
        "offer",
        None,
        None,
        None,
    )

    application_tt.refresh_from_db()
    interview_tt.refresh_from_db()
    assert application_tt.offer_date == datetime(2025, 11, 7).date()
    assert application_tt.status == "offer"
    assert interview_tt.offer_date is None


def test_compliance_prescreen_attaches_to_unique_active_application():
    company = Company.objects.create(
        name="Maximus",
        domain="maximus.com",
        first_contact=timestamp,
        last_contact=timestamp,
    )
    active_tt = ThreadTracking.objects.create(
        thread_id="t-active-app",
        company=company,
        company_source="subject_parse",
        job_title="Senior Cybersecurity Engineer",
        job_id="",
        status="application",
        sent_date=datetime(2026, 2, 20).date(),
        ml_label="job_application",
        ml_confidence=0.99,
        reviewed=False,
    )
    ThreadTracking.objects.create(
        thread_id="t-withdrawn-app",
        company=company,
        company_source="subject_parse",
        job_title="Senior Information System Security Specialist",
        job_id="",
        status="rejected",
        sent_date=datetime(2026, 2, 20).date(),
        rejection_date=datetime(2026, 2, 22).date(),
        withdrew=True,
        ml_label="job_application",
        ml_confidence=0.99,
        reviewed=False,
    )

    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0

        def save(self):
            pass

    milestone_timestamp = make_aware(datetime(2026, 2, 24, 16, 57, 6))
    metadata = {
        "thread_id": "t-compliance-prescreen",
        "timestamp": milestone_timestamp,
        "sender_domain": "threatswitch.com",
        "subject": "[Compliance] You've been asked to complete a form",
        "body": "Your security manager has requested that you complete the form, Maximus Federal Services Pre-screen 2025.",
    }

    _update_thread_tracking_for_company(
        "m-compliance-prescreen",
        metadata,
        {"confidence": 0.95},
        company,
        "subject_parse",
        {"job_title": "", "job_id": ""},
        "application",
        False,
        Stats(),
        "prescreen",
        None,
        None,
        milestone_timestamp.date(),
    )

    active_tt.refresh_from_db()
    assert active_tt.prescreen_date == datetime(2026, 2, 24).date()
