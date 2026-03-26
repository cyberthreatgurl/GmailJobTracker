"""Tests for EML import duplicate detection.

When importing an .eml file that matches an existing Gmail-ingested message
(same subject, sender domain, date), the EML import should reuse the existing
message's identifiers instead of creating duplicate Messages and orphan
ThreadTracking records.
"""

import pytest
from datetime import date
from pathlib import Path
from django.utils import timezone

from tracker.models import Message, Company, ThreadTracking

pytestmark = pytest.mark.django_db


def _build_eml(subject, sender, date_str, body="Test body"):
    """Build a minimal .eml string."""
    return (
        f"From: {sender}\r\n"
        f"To: user@example.com\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {date_str}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}"
    )


class TestEmlDuplicateDetection:
    """EML import should detect and reuse existing Gmail message identifiers."""

    def test_eml_import_reuses_gmail_thread_id(self):
        """Importing an EML matching an existing Gmail message should not create
        a duplicate Message with a synthetic eml_* msg_id."""
        from parser import ingest_message_from_eml

        now = timezone.now()
        company = Company.objects.create(name="Acme Corp", first_contact=now, last_contact=now)

        # Simulate a message already ingested from Gmail
        Message.objects.create(
            msg_id="18abc123def456",
            thread_id="19xyz789thread",
            subject="Your application to Acme Corp",
            sender="noreply@acme.com",
            timestamp=timezone.make_aware(
                timezone.datetime(2026, 2, 18, 10, 0, 0)
            ),
            body="Thank you for applying to Acme Corp.",
            company=company,
            ml_label="job_application",
            confidence=0.95,
            reviewed=True,
        )

        # Import same email as .eml
        eml = _build_eml(
            subject="Your application to Acme Corp",
            sender="noreply@acme.com",
            date_str="Wed, 18 Feb 2026 10:00:00 +0000",
            body="Thank you for applying to Acme Corp.",
        )
        ingest_message_from_eml(eml)

        # Should NOT have created a new message with eml_* msg_id
        eml_messages = Message.objects.filter(msg_id__startswith="eml_")
        assert eml_messages.count() == 0, (
            f"Expected no eml_* messages but found {eml_messages.count()}: "
            f"{list(eml_messages.values_list('msg_id', flat=True))}"
        )

        # Total messages should still be 1
        assert Message.objects.count() == 1

    def test_eml_import_does_not_create_orphan_thread_tracking(self):
        """EML import of a rejection matching an existing Gmail message should
        update the existing ThreadTracking, not create an orphan."""
        from parser import ingest_message_from_eml

        now = timezone.now()
        company = Company.objects.create(name="TestCo", first_contact=now, last_contact=now)

        # Existing Gmail message and ThreadTracking
        Message.objects.create(
            msg_id="18abc000gmail",
            thread_id="19thread000real",
            subject="Thank you for your interest in TestCo",
            sender="careers@testco.com",
            timestamp=timezone.make_aware(
                timezone.datetime(2026, 2, 15, 9, 0, 0)
            ),
            body="We decided to move forward with candidates whose experiences "
                 "more closely match our current needs.",
            company=company,
            ml_label="job_application",
            confidence=0.90,
            reviewed=False,
        )

        ThreadTracking.objects.create(
            thread_id="19thread000real",
            company=company,
            status="application",
            sent_date=date(2026, 2, 10),
        )

        # Import the same email as .eml (should be classified as rejection)
        eml = _build_eml(
            subject="Thank you for your interest in TestCo",
            sender="careers@testco.com",
            date_str="Sat, 15 Feb 2026 09:00:00 +0000",
            body="We decided to move forward with candidates whose experiences "
                 "more closely match our current needs.",
        )
        ingest_message_from_eml(eml)

        # Should NOT have created any eml_* ThreadTracking records
        eml_tts = ThreadTracking.objects.filter(thread_id__startswith="eml_")
        assert eml_tts.count() == 0, (
            f"Expected no eml_* ThreadTracking but found {eml_tts.count()}: "
            f"{list(eml_tts.values_list('thread_id', flat=True))}"
        )

        # Total ThreadTrackings should still be 1
        assert ThreadTracking.objects.count() == 1

    def test_eml_import_no_match_creates_normally(self):
        """When no matching Gmail message exists, EML import should create
        a new message with the synthetic eml_* identifiers as before."""
        from parser import ingest_message_from_eml

        eml = _build_eml(
            subject="Welcome to FreshCo - Application Received",
            sender="hr@freshco.com",
            date_str="Mon, 20 Feb 2026 12:00:00 +0000",
            body="Thank you for applying to FreshCo for the Software Engineer role.",
        )
        result = ingest_message_from_eml(eml)

        # Should create a message (either inserted or skipped if noise)
        total = Message.objects.count()
        if result == "inserted":
            assert total >= 1
            msg = Message.objects.first()
            assert msg.msg_id.startswith("eml_")
            assert msg.thread_id == msg.msg_id  # thread_id = fake_msg_id

    def test_eml_import_forwarded_message_uses_inner_forwarded_date(self):
        """Forwarded .eml imports should use the original message date."""
        from parser import ingest_message_from_eml

        eml = Path("tests/emails/Thank you for Applying to Amazon-2025.eml").read_text(
            encoding="utf-8",
            errors="replace",
        )

        result = ingest_message_from_eml(
            eml,
            fake_msg_id="eml_forwarded_amazon_2025_test",
        )

        assert result == "inserted"
        msg = Message.objects.get(msg_id="eml_forwarded_amazon_2025_test")
        local_timestamp = timezone.localtime(msg.timestamp)
        assert local_timestamp.date() == date(2025, 3, 6)
        assert local_timestamp.hour == 20
        assert local_timestamp.minute == 41
        assert msg.sender == "<noreply@mail.amazon.jobs>"
        assert msg.subject == "Thank you for Applying to Amazon!"
        assert msg.ml_label == "job_application"
        assert msg.company is not None
        assert msg.company.name == "Amazon"

    def test_eml_reingest_updates_existing_threadtracking_metadata(self):
        """Re-importing an existing forwarded EML should refresh the TT metadata."""
        from parser import ingest_message_from_eml

        now = timezone.now()
        company = Company.objects.create(name="Amazon", first_contact=now, last_contact=now)
        Message.objects.create(
            msg_id="eml_forwarded_existing_amazon",
            thread_id="eml_forwarded_existing_amazon",
            subject="Fwd: Thank you for Applying to Amazon!",
            sender="Kelly Shaw <cyberintelgurl@gmail.com>",
            timestamp=timezone.make_aware(timezone.datetime(2025, 3, 10, 9, 57, 54)),
            body="forwarded body",
            company=company,
            ml_label="job_application",
            confidence=1.0,
        )
        tt = ThreadTracking.objects.create(
            thread_id="eml_forwarded_existing_amazon",
            company=company,
            company_source="eml_import",
            job_title="Wrong Title",
            job_id="",
            status="application",
            sent_date=date(2025, 3, 10),
            ml_label="job_application",
        )

        eml = Path("tests/emails/Thank you for Applying to Amazon-2025.eml").read_text(
            encoding="utf-8",
            errors="replace",
        )

        result = ingest_message_from_eml(
            eml,
            fake_msg_id="eml_forwarded_existing_amazon",
        )

        assert result == "skipped"
        tt.refresh_from_db()
        assert tt.job_title == "Technical Program Manager , Red Team & Threat Intelligence (ID: 2909847)"
        assert tt.job_id == "2909847"
        assert tt.sent_date == date(2025, 3, 6)

    def test_eml_duplicate_noise_keeps_domain_mapped_company(self):
        """Duplicate EML updates should keep strong company matches even for noise."""
        from parser import ingest_message_from_eml

        now = timezone.now()
        Message.objects.create(
            msg_id="19b14d7653cb21d0",
            thread_id="19b14d7653cb21d0",
            subject="Profile submitted to Idaho National Laboratory",
            sender="Idaho National Laboratory <staffing@inl.gov>",
            timestamp=timezone.make_aware(
                timezone.datetime(2025, 12, 12, 23, 13, 38)
            ),
            body=(
                "We have received the profile you submitted to our company. "
                "Please review our current job opportunities and apply online to be considered for employment."
            ),
            ml_label="noise",
            confidence=1.0,
            reviewed=False,
        )
        Company.objects.create(
            name="Idaho National Laboratory",
            domain="inl.gov",
            first_contact=now,
            last_contact=now,
        )

        eml = Path("tests/emails/Profile submitted to Idaho National Laboratory.eml").read_text(
            encoding="utf-8",
            errors="replace",
        )

        result = ingest_message_from_eml(eml)

        msg = Message.objects.get(msg_id="19b14d7653cb21d0")
        assert result == "skipped"
        assert msg.company is not None
        assert msg.company.name == "Idaho National Laboratory"
        assert msg.company_source == "domain_mapping"

    def test_eml_different_sender_domain_not_matched(self):
        """EML with same subject/date but different sender domain should NOT
        be matched to an existing Gmail message."""
        from parser import ingest_message_from_eml

        now = timezone.now()
        company = Company.objects.create(name="SameName Inc", first_contact=now, last_contact=now)

        # Existing Gmail message from sender@alpha.com
        Message.objects.create(
            msg_id="18abc999gmail",
            thread_id="19thread999real",
            subject="Your application status",
            sender="hr@alpha.com",
            timestamp=timezone.make_aware(
                timezone.datetime(2026, 2, 18, 14, 0, 0)
            ),
            body="Thank you for applying.",
            company=company,
            ml_label="job_application",
            confidence=0.90,
        )

        # Import .eml from sender@beta.com (different domain, same subject/date)
        eml = _build_eml(
            subject="Your application status",
            sender="hr@beta.com",
            date_str="Wed, 18 Feb 2026 14:00:00 +0000",
            body="Thank you for applying.",
        )
        ingest_message_from_eml(eml)

        # Should have created a new eml_* message (different sender domain)
        msgs = Message.objects.all()
        assert msgs.count() == 2, f"Expected 2 messages, got {msgs.count()}"
        eml_msgs = Message.objects.filter(msg_id__startswith="eml_")
        assert eml_msgs.count() == 1
