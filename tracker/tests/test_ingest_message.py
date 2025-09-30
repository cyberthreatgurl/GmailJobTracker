# test_ingest_message.py
import pytest
from parser import ingest_message, log_ignored_message
from db import is_valid_company

pytestmark = pytest.mark.django_db

def test_ingest_ignored_reason_logging(monkeypatch, fake_stats, fake_message_model):
    captured = {}

    # Patch log_ignored_message to capture its arguments
    monkeypatch.setattr("parser.log_ignored_message", lambda msg_id, metadata, reason: captured.update({
        "msg_id": msg_id,
        "reason": reason,
        "subject": metadata["subject"],
        "sender": metadata["sender"]
    }))

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t8",
        "sender": "x", "sender_domain": "example.com",
        "timestamp": "now", "labels": [], "last_updated": "now"
    })
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

    # Parsed subject flags the message as ignored
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": True,
        "ignore_reason": "ml_ignore",
        "company": "", "job_title": "", "job_id": ""
    })

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
        def save(self): pass
    return Stats()

@pytest.fixture
def fake_message_model(monkeypatch):
    class FakeQuerySet:
        def __init__(self, exists=False): self._exists = exists
        def exists(self): return self._exists

    class FakeManager:
        def __init__(self): self.created = []
        def filter(self, **kwargs): return FakeQuerySet(exists=False)
        def create(self, **kwargs): self.created.append(kwargs)

    fake_manager = FakeManager()
    
    class FakeMessage:
        objects = fake_manager

    # Patch parser.Message with our fake class
    monkeypatch.setattr("parser.Message", FakeMessage)

    return fake_manager

    
def test_ingest_ignored(monkeypatch, fake_stats, fake_message_model):
    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {"subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t1", "sender": "x", "sender_domain": "y", "timestamp": "now", "labels": [], "last_updated": "now"})
    monkeypatch.setattr("parser.classify_message", lambda b: None)
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {"response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None})
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {"ignore": True})
    monkeypatch.setattr("parser.log_ignored_message", lambda *a, **k: None)
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m1")
    assert result == "ignored"
    assert fake_stats.total_ignored == 1

def test_ingest_skipped(monkeypatch, fake_stats, fake_message_model):
    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {"subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t1", "sender": "x", "sender_domain": "y", "timestamp": "now", "labels": [], "last_updated": "now"})
    monkeypatch.setattr("parser.classify_message", lambda b: None)
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {"response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None})
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {"ignore": False})
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    # Force duplicate
    fake_message_model.filter = lambda **kwargs: type("Q", (), {"exists": lambda self: True})()

    result = ingest_message(None, "m2")
    assert result == "skipped"
    assert fake_stats.total_skipped == 1

def test_ingest_inserted(monkeypatch, fake_stats, fake_message_model):
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t1",
        "sender": "x", "sender_domain": "y", "timestamp": "now", "labels": [], "last_updated": "now"
    })
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False, "company": "TestCo", "job_title": "Engineer", "job_id": "123"
    })
    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m3")
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    assert len(fake_message_model.created) == 1
    assert fake_message_model.created[0]["subject"] == "foo"
    assert fake_message_model.created[0]["thread_id"] == "t1"

    assert captured_record["company"] == "TestCo"
    assert captured_record["job_title"] == "Engineer"
    assert captured_record["company_job_index"] == "test_index"

def test_ingest_domain_mapping(monkeypatch, fake_stats, fake_message_model):
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))
    monkeypatch.setattr("parser.DOMAIN_TO_COMPANY", {"example.com": "MappedCo"})

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t1",
        "sender": "x", "sender_domain": "example.com", "timestamp": "now", "labels": [], "last_updated": "now"
    })
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False, "company": "", "job_title": "Engineer", "job_id": "123"
    })
    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m4")
    assert result == "inserted"
    assert fake_stats.total_inserted == 1
    assert captured_record["company"] == "MappedCo"
    assert captured_record["company_source"] == "domain_mapping"


def test_ingest_subject_parse(monkeypatch, fake_stats, fake_message_model):
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t1",
        "sender": "x", "sender_domain": "y", "timestamp": "now", "labels": [], "last_updated": "now"
    })
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False, "company": "TestCo", "job_title": "Engineer", "job_id": "123"
    })
    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m3")
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    # ✅ Verify the inserted message content
    assert len(fake_message_model.created) == 1
    assert fake_message_model.created[0]["subject"] == "foo"
    assert fake_message_model.created[0]["thread_id"] == "t1"

    # ✅ Verify the final record
    assert captured_record["company"] == "TestCo"
    assert captured_record["company_source"] == "subject_parse"
    assert captured_record["job_title"] == "Engineer"
    assert captured_record["company_job_index"] == "test_index"
    assert captured_record["subject"] == "foo"
    assert captured_record["status"] == "applied"
    
def test_ingest_sender_name_match(monkeypatch, fake_stats, fake_message_model):
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))

    # Patch known companies
    monkeypatch.setattr("parser.KNOWN_COMPANIES", ["Airbnb"])

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t6",
        "sender": "Airbnb Recruiting <jobs@airbnb.com>", "sender_domain": "airbnb.com",
        "timestamp": "now", "labels": [], "last_updated": "now"
    })
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

    # No company in parsed subject
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False, "company": "", "job_title": "Engineer", "job_id": "123"
    })
    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m6")
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    assert captured_record["company"] == "Airbnb"
    assert captured_record["company_source"] == "sender_name_match"
    assert captured_record["job_title"] == "Engineer"
    assert captured_record["company_job_index"] == "test_index"    
    
def test_ingest_company_rejection(monkeypatch, fake_stats, fake_message_model):
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))

    # Patch known companies and validation logic from db
    monkeypatch.setattr("parser.KNOWN_COMPANIES", [])
    monkeypatch.setattr("db.is_valid_company", lambda name: False)

    # Patch domain mapping to catch fallback
    monkeypatch.setattr("parser.DOMAIN_TO_COMPANY", {"example.com": "FallbackCo"})

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo", "body": "bar", "date": "2025-09-29", "thread_id": "t7",
        "sender": "x", "sender_domain": "example.com",
        "timestamp": "now", "labels": [], "last_updated": "now"
    })
    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None, "follow_up_dates": [], "rejection_date": None, "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

    # Parsed subject returns a bad company name
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False, "company": "careers", "job_title": "Engineer", "job_id": "123"
    })
    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "test_index")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m7")
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    # ✅ Confirm company was rejected and fallback used
    assert captured_record["company"] == "FallbackCo"
    assert captured_record["company_source"] == "domain_mapping"
    
def test_ingest_ml_fallback(monkeypatch, fake_stats, fake_message_model):
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))

    # Patch ML prediction directly
    monkeypatch.setattr("parser.predict_company", lambda body: "MLCo")

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo",
        "body": "This is a job application email",
        "date": "2025-09-29",
        "thread_id": "t9",
        "sender": "x",
        "sender_domain": "unknown.com",
        "timestamp": "now",
        "labels": [],
        "last_updated": "now"
    })

    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": None,
        "follow_up_dates": [],
        "rejection_date": None,
        "interview_date": None
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

    # Parsed subject returns no company
    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False,
        "company": "",
        "job_title": "Engineer",
        "job_id": "123"
    })

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
    captured_record = {}
    monkeypatch.setattr("parser.insert_or_update_application", lambda record: captured_record.update(record))

    monkeypatch.setattr("parser.extract_metadata", lambda s, m: {
        "subject": "foo",
        "body": "This is a job application email",
        "date": "2025-09-29",
        "thread_id": "t10",
        "sender": "x",
        "sender_domain": "example.com",
        "timestamp": "now",
        "labels": ["inbox", "jobs"],
        "last_updated": "now"
    })

    monkeypatch.setattr("parser.classify_message", lambda b: "applied")
    monkeypatch.setattr("parser.extract_status_dates", lambda b, d: {
        "response_date": "2025-09-30",
        "follow_up_dates": ["2025-10-02"],
        "rejection_date": None,
        "interview_date": "2025-10-05"
    })
    monkeypatch.setattr("parser.insert_email_text", lambda *a, **k: None)

    monkeypatch.setattr("parser.parse_subject", lambda *a, **k: {
        "ignore": False,
        "company": "TestCorp",
        "job_title": "Engineer",
        "job_id": "123",
        "predicted_company": "TestCorp"
    })

    monkeypatch.setattr("parser.build_company_job_index", lambda *a, **k: "testcorp_engineer_123")
    monkeypatch.setattr("parser.get_stats", lambda: fake_stats)

    result = ingest_message(None, "m10")
    assert result == "inserted"
    assert fake_stats.total_inserted == 1

    # ✅ Confirm full record shape
    assert captured_record == {
        "thread_id": "t10",
        "company": "TestCorp",
        "predicted_company": "TestCorp",
        "job_title": "Engineer",
        "job_id": "123",
        "first_sent": "2025-09-29",
        "response_date": "2025-09-30",
        "follow_up_dates": ["2025-10-02"],
        "rejection_date": None,
        "interview_date": "2025-10-05",
        "status": "applied",
        "labels": ["inbox", "jobs"],
        "subject": "foo",
        "sender": "x",
        "sender_domain": "example.com",
        "last_updated": "now",
        "company_source": "subject_parse",
        "company_job_index": "testcorp_engineer_123"
    }