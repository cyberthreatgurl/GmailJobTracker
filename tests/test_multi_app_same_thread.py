"""Regression tests for multiple applications on the same Gmail thread.

When Gmail groups messages with identical subjects (e.g., generic ATS
confirmation "Application Complete - Thank You For Applying") into the
same thread, each application should still get its own ThreadTracking
record. The second application gets a TT keyed by its msg_id rather
than the shared Gmail thread_id.

Tests cover:
1. parser.py: _create_thread_tracking_for_application creates separate TTs
2. label_propagation.py: propagate_message_label_to_thread creates separate TTs
3. views/companies.py: Company Data Preview query finds both TTs
"""

import datetime
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from tracker.models import Company, Message, ThreadTracking, IngestionStats


SHARED_THREAD_ID = "aaaa1111bbbb2222"
FIRST_MSG_ID = SHARED_THREAD_ID  # First message's msg_id == thread_id (Gmail convention)
SECOND_MSG_ID = "cccc3333dddd4444"


@pytest.fixture
def company(db):
    """Create a test company."""
    now = timezone.now()
    return Company.objects.create(
        name="Maximus",
        domain="maximus.com",
        first_contact=now,
        last_contact=now,
    )


@pytest.fixture
def stats(db):
    """Create a real IngestionStats record for today."""
    today = timezone.localdate()
    obj, _ = IngestionStats.objects.get_or_create(date=today)
    return obj


@pytest.fixture
def first_tt(company):
    """ThreadTracking created for the first application (thread_id == msg_id)."""
    return ThreadTracking.objects.create(
        thread_id=SHARED_THREAD_ID,
        company=company,
        company_source="domain_mapping",
        job_title="",
        job_id="",
        status="application",
        sent_date=datetime.date(2026, 2, 20),
        ml_label="job_application",
        ml_confidence=0.95,
    )


@pytest.fixture
def first_message(company):
    """First application message (msg_id == thread_id)."""
    return Message.objects.create(
        msg_id=FIRST_MSG_ID,
        thread_id=SHARED_THREAD_ID,
        company=company,
        company_source="domain_mapping",
        sender="noreply@maximus.com",
        subject="Application Complete - Thank You For Applying",
        body="Thank you for applying to Maximus.",
        timestamp=timezone.now() - datetime.timedelta(minutes=16),
        ml_label="job_application",
        confidence=0.95,
    )


@pytest.fixture
def second_message(company):
    """Second application message (different msg_id, same thread_id)."""
    return Message.objects.create(
        msg_id=SECOND_MSG_ID,
        thread_id=SHARED_THREAD_ID,
        company=company,
        company_source="domain_mapping",
        sender="noreply@maximus.com",
        subject="Application Complete - Thank You For Applying",
        body="Thank you for applying to Maximus.",
        timestamp=timezone.now(),
        ml_label="job_application",
        confidence=0.93,
    )


# ==============================================================================
# Tests for _create_thread_tracking_for_application (parser.py)
# ==============================================================================


class TestParserMultiAppPerThread:
    """Test that the parser creates separate TTs for multiple applications on one thread."""

    def _make_metadata(self, timestamp=None):
        return {
            "thread_id": SHARED_THREAD_ID,
            "timestamp": timestamp or timezone.now(),
            "subject": "Application Complete - Thank You For Applying",
            "body": "Thank you for applying to Maximus.",
            "sender_domain": "maximus.com",
        }

    def _make_result(self):
        return {"label": "job_application", "confidence": 0.93}

    def test_second_application_creates_separate_tt(self, company, first_tt, stats):
        """A second job_application on the same thread should create a new TT with msg_id."""
        from parser import _create_thread_tracking_for_application
        metadata = self._make_metadata()
        result = self._make_result()

        _create_thread_tracking_for_application(
            msg_id=SECOND_MSG_ID,
            metadata=metadata,
            result=result,
            company_obj=company,
            company_source="domain_mapping",
            parsed_subject={"job_title": "", "job_id": ""},
            status="application",
            reviewed=False,
            stats=stats,
            ml_label="job_application",
            rejection_date_final=None,
            interview_date_final=None,
            prescreen_date_final=None,
        )

        # Should now be 2 TTs
        tts = ThreadTracking.objects.filter(company=company)
        assert tts.count() == 2

        # Second TT should use msg_id as thread_id
        second_tt = ThreadTracking.objects.filter(thread_id=SECOND_MSG_ID).first()
        assert second_tt is not None
        assert second_tt.ml_label == "job_application"

    def test_first_message_creates_normally(self, company, stats):
        """The first application on a fresh thread should create TT with thread_id."""
        from parser import _create_thread_tracking_for_application
        metadata = self._make_metadata()
        result = self._make_result()

        _create_thread_tracking_for_application(
            msg_id=FIRST_MSG_ID,
            metadata=metadata,
            result=result,
            company_obj=company,
            company_source="domain_mapping",
            parsed_subject={"job_title": "", "job_id": ""},
            status="application",
            reviewed=False,
            stats=stats,
            ml_label="job_application",
            rejection_date_final=None,
            interview_date_final=None,
            prescreen_date_final=None,
        )

        tt = ThreadTracking.objects.filter(thread_id=SHARED_THREAD_ID).first()
        assert tt is not None
        assert tt.ml_label == "job_application"

    def test_no_duplicate_on_reingest_same_message(self, company, first_tt, stats):
        """Re-ingesting the SAME message (msg_id == thread_id) should NOT create a duplicate."""
        from parser import _create_thread_tracking_for_application
        metadata = self._make_metadata()
        result = self._make_result()

        _create_thread_tracking_for_application(
            msg_id=FIRST_MSG_ID,  # Same as thread_id
            metadata=metadata,
            result=result,
            company_obj=company,
            company_source="domain_mapping",
            parsed_subject={"job_title": "", "job_id": ""},
            status="application",
            reviewed=False,
            stats=stats,
            ml_label="job_application",
            rejection_date_final=None,
            interview_date_final=None,
            prescreen_date_final=None,
        )

        assert ThreadTracking.objects.filter(company=company).count() == 1

    def test_rejection_does_not_trigger_multi_app(self, company, first_tt, stats):
        """A rejection on the same thread should update, not create a new TT."""
        from parser import _create_thread_tracking_for_application
        metadata = self._make_metadata()
        result = {"label": "rejection", "confidence": 0.90}

        _create_thread_tracking_for_application(
            msg_id=SECOND_MSG_ID,
            metadata=metadata,
            result=result,
            company_obj=company,
            company_source="domain_mapping",
            parsed_subject={"job_title": "", "job_id": ""},
            status="rejected",
            reviewed=False,
            stats=stats,
            ml_label="rejection",
            rejection_date_final=datetime.date(2026, 2, 20),
            interview_date_final=None,
            prescreen_date_final=None,
        )

        # Should still be just 1 TT (rejection updates existing, doesn't create)
        assert ThreadTracking.objects.filter(company=company).count() == 1

    def test_third_application_also_gets_own_tt(self, company, first_tt, stats):
        """A third application on the same thread also creates its own TT."""
        from parser import _create_thread_tracking_for_application
        metadata = self._make_metadata()
        result = self._make_result()

        # Create second
        _create_thread_tracking_for_application(
            msg_id=SECOND_MSG_ID,
            metadata=metadata,
            result=result,
            company_obj=company,
            company_source="domain_mapping",
            parsed_subject={"job_title": "", "job_id": ""},
            status="application",
            reviewed=False,
            stats=stats,
            ml_label="job_application",
            rejection_date_final=None,
            interview_date_final=None,
            prescreen_date_final=None,
        )

        # Create third
        third_msg_id = "eeee5555ffff6666"
        _create_thread_tracking_for_application(
            msg_id=third_msg_id,
            metadata=metadata,
            result=result,
            company_obj=company,
            company_source="domain_mapping",
            parsed_subject={"job_title": "", "job_id": ""},
            status="application",
            reviewed=False,
            stats=stats,
            ml_label="job_application",
            rejection_date_final=None,
            interview_date_final=None,
            prescreen_date_final=None,
        )

        assert ThreadTracking.objects.filter(company=company).count() == 3


# ==============================================================================
# Tests for propagate_message_label_to_thread (label_propagation.py)
# ==============================================================================


class TestPropagateMultiAppPerThread:
    """Test that propagation creates separate TTs for multi-app threads."""

    def test_propagation_creates_separate_tt_for_second_app(
        self, company, first_tt, second_message
    ):
        """propagate_message_label_to_thread should create separate TT for 2nd app."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        result = propagate_message_label_to_thread(second_message)

        assert result is not None
        assert result.thread_id == SECOND_MSG_ID
        assert ThreadTracking.objects.filter(company=company).count() == 2

    def test_propagation_does_not_duplicate_on_rerun(
        self, company, first_tt, second_message
    ):
        """Running propagation twice for the same message should not create duplicates."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        propagate_message_label_to_thread(second_message)
        propagate_message_label_to_thread(second_message)

        assert ThreadTracking.objects.filter(company=company).count() == 2

    def test_propagation_updates_existing_first_app_normally(
        self, company, first_tt, first_message
    ):
        """For the first message (msg_id == thread_id), normal update should occur."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        first_message.confidence = 0.99
        first_message.save()

        result = propagate_message_label_to_thread(first_message)

        assert result is not None
        assert result.thread_id == SHARED_THREAD_ID
        assert ThreadTracking.objects.filter(company=company).count() == 1


# ==============================================================================
# Tests for Company Data Preview query (views/companies.py)
# ==============================================================================


class TestCompanyDataPreviewQuery:
    """Test that the Company Data Preview finds TTs keyed by both thread_id and msg_id."""

    def test_query_finds_both_tts(
        self, company, first_tt, first_message, second_message
    ):
        """Both TTs should be found via the combined thread_id + msg_id lookup."""
        from django.db.models import Q

        # Create the second TT (keyed by msg_id)
        second_tt = ThreadTracking.objects.create(
            thread_id=SECOND_MSG_ID,
            company=company,
            company_source="domain_mapping",
            job_title="",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 20),
            ml_label="job_application",
            ml_confidence=0.93,
        )

        # Replicate the query from companies.py
        app_messages = Message.objects.filter(
            company=company,
            ml_label="job_application",
        )
        application_thread_ids = set(
            app_messages.values_list("thread_id", flat=True).distinct()
        )
        application_msg_ids = set(
            app_messages.values_list("msg_id", flat=True).distinct()
        )
        all_tt_lookup_ids = application_thread_ids | application_msg_ids

        application_threads = list(
            ThreadTracking.objects.filter(
                Q(company=company) & Q(thread_id__in=all_tt_lookup_ids)
            ).order_by("-sent_date")
        )

        assert len(application_threads) == 2
        tt_thread_ids = {tt.thread_id for tt in application_threads}
        assert SHARED_THREAD_ID in tt_thread_ids
        assert SECOND_MSG_ID in tt_thread_ids

    def test_old_query_misses_msgid_tt(
        self, company, first_tt, first_message, second_message
    ):
        """The OLD query (thread_id only) would miss the msg_id-keyed TT."""
        # Create the second TT (keyed by msg_id)
        ThreadTracking.objects.create(
            thread_id=SECOND_MSG_ID,
            company=company,
            company_source="domain_mapping",
            job_title="",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 20),
            ml_label="job_application",
            ml_confidence=0.93,
        )

        # Old query: only uses Message.thread_id
        application_thread_ids = Message.objects.filter(
            company=company,
            ml_label="job_application",
        ).values_list("thread_id", flat=True).distinct()

        old_results = list(
            ThreadTracking.objects.filter(
                company=company,
                thread_id__in=application_thread_ids,
            ).order_by("-sent_date")
        )

        # Old query should only find 1 (proving the bug existed)
        assert len(old_results) == 1
        assert old_results[0].thread_id == SHARED_THREAD_ID
