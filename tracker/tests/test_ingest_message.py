# test_ingest_message.py
from datetime import datetime
from parser import ingest_message, parse_subject

import pytest
from django.utils.timezone import make_aware

from tracker.tests.test_helpers import FakeMessageRecord

pytestmark = pytest.mark.django_db
timestamp = make_aware(datetime(2025, 9, 29, 12, 0))


def test_ingest_ignored_reason_logging(monkeypatch, fake_stats, fake_message_model):
    queryset, manager = fake_message_model
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
        lambda s, m: {
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
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

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
    assert result == "ignored"
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
    queryset, manager = fake_message_model
    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m: {
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
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {"ignore": True})
    monkeypatch.setattr("parser.log_ignored_message", lambda *a, **k: None)
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m1")
    assert result == "ignored"
    assert fake_stats.total_ignored == 1


def test_ingest_skipped(monkeypatch, fake_stats, fake_message_model):
    queryset, manager = fake_message_model
    timestamp = make_aware(datetime(2025, 9, 29, 12, 0))

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m: {
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
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {"ignore": False})
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    queryset, manager = fake_message_model
    queryset.set_first(FakeMessageRecord({"msg_id": "m2"}))

    result = ingest_message(None, "m2")
    assert result == "skipped"
    assert fake_stats.total_skipped == 1


def test_thank_you_message_does_not_set_interview_date(
    monkeypatch, fake_stats, fake_message_model
):
    """Regression test: a simple 'thank you for applying' message should not create an interview_date.

    This prevents false positives where automated acknowledgement/rejection emails are interpreted
    as scheduled interviews.
    """
    queryset, manager = fake_message_model
    captured_record = {}

    monkeypatch.setattr(
        "parser.insert_or_update_application",
        lambda record: captured_record.update(record),
    )

    # Simulate a typical 'thank you for applying' message
    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m: {
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

    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.classify_message", lambda b: None)
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m_thanks")
    assert result == "inserted"
    # Regression: ensure interview_date is not set from this acknowledgement message
    assert captured_record.get("interview_date") is None


def test_ingest_subject_parse(monkeypatch, fake_stats, fake_message_model):
    queryset, manager = fake_message_model
    captured_record = {}
    monkeypatch.setattr(
        "parser.insert_or_update_application",
        lambda record: captured_record.update(record),
    )

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m: {
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
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
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
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    assert len(manager.created) == 1
    # ✅ Verify the inserted message content
    assert manager.created[0]["subject"] == "foo"
    assert manager.created[0]["thread_id"] == "t1"

    # ✅ Verify the final record
    assert captured_record["company"] == "TestCo"
    assert captured_record["company_source"] == "subject_parse"
    assert captured_record["job_title"] == "Engineer"
    assert captured_record["company_job_index"] == "test_index"
    assert captured_record["subject"] == "foo"
    assert captured_record["status"] == "applied"




def test_ingest_ml_fallback(monkeypatch, fake_stats, fake_message_model):
    queryset, manager = fake_message_model
    captured_record = {}
    monkeypatch.setattr(
        "parser.insert_or_update_application",
        lambda record: captured_record.update(record),
    )

    # Patch ML prediction directly
    monkeypatch.setattr("parser.predict_company", lambda subject, body: "MLCo")
    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m: {
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
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

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
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    # ✅ Confirm ML prediction was used
    assert captured_record["company"] == "MLCo"
    assert captured_record["company_source"] == "ml_prediction"
    assert captured_record["job_title"] == "Engineer"
    assert captured_record["company_job_index"] == "test_index"


def test_ingest_record_shape(monkeypatch, fake_stats, fake_message_model):
    queryset, manager = fake_message_model
    captured_record = {}
    monkeypatch.setattr(
        "parser.insert_or_update_application",
        lambda record: captured_record.update(record),
    )

    monkeypatch.setattr(
        "parser.extract_metadata",
        lambda s, m: {
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
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

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
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    # ✅ Verify full record schema (parser normalizes lists to comma-separated strings)
    assert captured_record["subject"] == "foo"
    assert captured_record["thread_id"] == "t10"
    assert captured_record["company"] == "TestCorp"
    assert captured_record["job_title"] == "Engineer"
    assert captured_record["company_job_index"] == "testcorp_engineer_123"
    assert captured_record["status"] == "applied"
    assert captured_record["company_source"] == "subject_parse"
    # Parser normalizes labels and follow_up_dates to strings
    assert captured_record["labels"] == "inbox, jobs"
    assert captured_record["follow_up_dates"] == "2025-10-02"
    # extract_status_dates returns None for these, not converted to dates
    assert captured_record["response_date"] is None
    assert captured_record["interview_date"] is None
