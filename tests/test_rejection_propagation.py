"""Regression tests for cross-thread rejection propagation.

Tests the fix for the scenario where a rejection email arrives on a different
thread than the original job application. We still support cross-thread updates,
but only when there is confident role-title evidence. This prevents one rejection
from marking unrelated same-company applications.

Also tests body-based cancellation detection (is_cancelled_position) during rejection
propagation, ensuring cancelled=True is set when the email body indicates the position
was cancelled rather than the applicant being rejected.
"""

import datetime
from unittest.mock import patch, MagicMock

import pytest
from django.utils import timezone

from tracker.models import Company, Message, ThreadTracking


@pytest.fixture
def company(db):
    """Create a test company."""
    now = timezone.now()
    return Company.objects.create(
        name="Booz Allen Hamilton",
        domain="bah.com",
        first_contact=now,
        last_contact=now,
    )


@pytest.fixture
def application_tt(company):
    """Create the real application ThreadTracking (the one that should be updated)."""
    return ThreadTracking.objects.create(
        thread_id="19c33c4469a95328",
        company=company,
        company_source="domain_mapping",
        job_title="Cyber Threat Intelligence Analyst, Senior",
        job_id="",
        status="application",
        sent_date=datetime.date(2026, 2, 6),
        ml_label="job_application",
        ml_confidence=0.95,
    )


@pytest.fixture
def spurious_tt(company):
    """Create the spurious ThreadTracking (created from misclassification)."""
    return ThreadTracking.objects.create(
        thread_id="19c7b42504ee5c72",
        company=company,
        company_source="domain_mapping",
        job_title="",
        job_id="",
        status="application",
        sent_date=datetime.date(2026, 2, 20),
        ml_label="job_application",
        ml_confidence=0.85,
    )


@pytest.fixture
def rejection_message(company):
    """Create the rejection Message (on spurious thread)."""
    return Message.objects.create(
        msg_id="msg_rejection_001",
        thread_id="19c7b42504ee5c72",
        company=company,
        company_source="domain_mapping",
        sender="workday@bah.com",
        subject="Application Status for Cyber Threat Intelligence Analyst, Senior",
        body=(
            "Thank you for your interest in Booz Allen Hamilton. "
            "After careful review, we will not be proceeding with your application "
            "due to the position being no longer available."
        ),
        timestamp=timezone.now(),
        ml_label="rejection",
        confidence=0.92,
    )


# ==============================================================================
# Tests for propagate_message_label_to_thread()
# ==============================================================================


class TestPropagateRejectionCrossThread:
    """Test scoped cross-thread behavior for rejection propagation."""

    def test_rejection_propagates_to_actual_application(
        self, company, application_tt, spurious_tt, rejection_message
    ):
        """The actual application TT should get rejection_date set."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        result = propagate_message_label_to_thread(rejection_message)

        # The function returns the thread_id-matched TT (spurious)
        assert result is not None
        assert result.thread_id == "19c7b42504ee5c72"

        # The spurious TT should be updated
        spurious_tt.refresh_from_db()
        assert spurious_tt.rejection_date is not None

        # CRITICAL: The actual application TT should ALSO be updated
        application_tt.refresh_from_db()
        assert application_tt.rejection_date is not None, (
            "Application TT should have rejection_date set via cross-thread propagation"
        )

    def test_cancelled_detected_from_body(
        self, company, application_tt, spurious_tt, rejection_message
    ):
        """'position being no longer available' in body should set cancelled=True."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        propagate_message_label_to_thread(rejection_message)

        # Both TTs should have cancelled=True
        spurious_tt.refresh_from_db()
        assert spurious_tt.cancelled is True, (
            "Spurious TT should have cancelled=True from body detection"
        )

        application_tt.refresh_from_db()
        assert application_tt.cancelled is True, (
            "Application TT should have cancelled=True from body detection"
        )

    def test_rejection_no_cross_thread_when_no_company(self, db, spurious_tt):
        """Without a company on the message, no cross-thread propagation should occur."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        msg = Message.objects.create(
            msg_id="msg_no_company",
            thread_id="19c7b42504ee5c72",
            company=None,
            sender="noreply@example.com",
            subject="Rejection",
            body="We will not be proceeding.",
            timestamp=timezone.now(),
            ml_label="rejection",
            confidence=0.9,
        )
        propagate_message_label_to_thread(msg)

        spurious_tt.refresh_from_db()
        assert spurious_tt.rejection_date is not None

    def test_does_not_overwrite_existing_rejection_date(
        self, company, spurious_tt, rejection_message
    ):
        """If a company's TT already has a rejection_date, don't overwrite it."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        # Create an application TT that already has a rejection_date
        existing_date = datetime.date(2026, 1, 15)
        app_tt = ThreadTracking.objects.create(
            thread_id="thread_already_rejected",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Engineer",
            job_id="",
            status="rejected",
            sent_date=datetime.date(2026, 1, 1),
            rejection_date=existing_date,
        )

        propagate_message_label_to_thread(rejection_message)

        app_tt.refresh_from_db()
        assert app_tt.rejection_date == existing_date, (
            "Pre-existing rejection_date should not be overwritten"
        )

    def test_propagation_only_updates_earliest_application(
        self, company, spurious_tt, rejection_message
    ):
        """Ambiguous matches should not update unrelated same-company applications."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        early_tt = ThreadTracking.objects.create(
            thread_id="thread_early",
            company=company,
            company_source="domain_mapping",
            job_title="Analyst I",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 1, 1),
        )
        late_tt = ThreadTracking.objects.create(
            thread_id="thread_late",
            company=company,
            company_source="domain_mapping",
            job_title="Analyst II",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 1),
        )

        propagate_message_label_to_thread(rejection_message)

        early_tt.refresh_from_db()
        late_tt.refresh_from_db()
        assert early_tt.rejection_date is None, (
            "Ambiguous fallback should not update unrelated application"
        )
        assert late_tt.rejection_date is None, (
            "Ambiguous fallback should not update unrelated application"
        )

    def test_updates_only_matching_role_when_company_has_multiple_applications(self, company):
        """A rejection should update only the matching role, not all company applications."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        cyber_tt = ThreadTracking.objects.create(
            thread_id="thread_cyber",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Cybersecurity Engineer",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 1),
            ml_label="job_application",
        )
        isss_tt = ThreadTracking.objects.create(
            thread_id="thread_isss",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Information System Security Specialist",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 2),
            ml_label="job_application",
        )

        msg = Message.objects.create(
            msg_id="msg_reject_cyber_only",
            thread_id="thread_spurious",
            company=company,
            sender="workday@bah.com",
            subject="Confirmation of withdraw from Senior Cybersecurity Engineer",
            body="We confirm your withdrawal request.",
            timestamp=timezone.now(),
            ml_label="rejection",
            confidence=0.94,
        )

        propagate_message_label_to_thread(msg)

        cyber_tt.refresh_from_db()
        isss_tt.refresh_from_db()
        assert cyber_tt.rejection_date is not None, (
            "Matching role should receive rejection update"
        )
        assert isss_tt.rejection_date is None, (
            "Non-matching role should not be marked rejected"
        )

    def test_thread_matched_role_does_not_propagate_to_other_company_role(self, company):
        """If thread-matched TT role already matches, do not touch other company roles."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        withdrawn_tt = ThreadTracking.objects.create(
            thread_id="thread_withdrawn_isss",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Information System Security Specialist",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 1),
            ml_label="job_application",
        )
        other_tt = ThreadTracking.objects.create(
            thread_id="thread_other_cyber",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Cybersecurity Engineer",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 2),
            ml_label="job_application",
        )

        msg = Message.objects.create(
            msg_id="msg_withdraw_isss_only",
            thread_id="thread_withdrawn_isss",
            company=company,
            sender="careers@bah.com",
            subject="Confirmation of withdraw from Senior Information System Security Specialist",
            body="You have successfully withdrawn from this position.",
            timestamp=timezone.now(),
            ml_label="rejection",
            confidence=0.96,
        )

        result = propagate_message_label_to_thread(msg)
        assert result is not None
        assert result.thread_id == "thread_withdrawn_isss"

        withdrawn_tt.refresh_from_db()
        other_tt.refresh_from_db()
        assert withdrawn_tt.rejection_date is not None, (
            "Withdrawn role should be marked rejected"
        )
        assert other_tt.rejection_date is None, (
            "Other same-company role must remain untouched"
        )

    def test_no_thread_id_match_falls_through_to_company(self, company, db):
        """When no TT exists for the thread_id, fall through to company-based lookup."""
        from tracker.utils.label_propagation import propagate_message_label_to_thread

        app_tt = ThreadTracking.objects.create(
            thread_id="thread_app_only",
            company=company,
            company_source="domain_mapping",
            job_title="Data Scientist",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 1, 10),
        )

        msg = Message.objects.create(
            msg_id="msg_no_thread_match",
            thread_id="thread_completely_new",
            company=company,
            sender="workday@bah.com",
            subject="Rejection for Data Scientist",
            body="Unfortunately, we are unable to offer you the position.",
            timestamp=timezone.now(),
            ml_label="rejection",
            confidence=0.90,
        )

        propagate_message_label_to_thread(msg)

        app_tt.refresh_from_db()
        assert app_tt.rejection_date is not None, (
            "Company-based fallback should find and update the application TT"
        )


# ==============================================================================
# Tests for is_cancelled_position() with new pattern
# ==============================================================================


class TestCancelledPatternExpansion:
    """Test that CANCELLED_PATTERNS now matches 'position no longer available'."""

    def test_position_being_no_longer_available(self, db):
        """'position being no longer available' should be detected as cancelled."""
        from parser_helpers import is_cancelled_position

        assert is_cancelled_position(
            "", "due to the position being no longer available"
        ) is True

    def test_position_is_no_longer_available(self, db):
        """'position is no longer available' should be detected as cancelled."""
        from parser_helpers import is_cancelled_position

        assert is_cancelled_position(
            "", "Unfortunately, the position is no longer available."
        ) is True

    def test_position_no_longer_available_in_subject(self, db):
        """Pattern should also match in the subject line."""
        from parser_helpers import is_cancelled_position

        assert is_cancelled_position(
            "Position is no longer available", ""
        ) is True

    def test_existing_patterns_still_work(self, db):
        """Existing CANCELLED_PATTERNS should still function."""
        from parser_helpers import is_cancelled_position

        assert is_cancelled_position("", "The role has been cancelled") is True
        assert is_cancelled_position("", "position has been closed") is True
        assert is_cancelled_position(
            "", "decided not to fill this role"
        ) is True
        assert is_cancelled_position("", "Thank you for applying") is False


# ==============================================================================
# Tests for _update_thread_tracking_on_reingest()
# ==============================================================================


class TestUpdateThreadTrackingOnReingest:
    """Test the reingest function's rejection propagation and cancellation detection."""

    def _make_metadata(self, thread_id="19c7b42504ee5c72"):
        """Build a minimal metadata dict for reingest."""
        return {
            "thread_id": thread_id,
            "timestamp": timezone.now(),
            "subject": "Application Status for Cyber Threat Intelligence Analyst, Senior",
            "body": (
                "Thank you for your interest. "
                "We will not be proceeding with your application "
                "due to the position being no longer available."
            ),
        }

    def test_reingest_sets_cancelled_on_spurious_tt(
        self, company, application_tt, spurious_tt
    ):
        """During reingest, placeholder TT should stay untouched when a role match exists."""
        from parser import _update_thread_tracking_on_reingest

        metadata = self._make_metadata()
        result = {"label": "rejection", "confidence": 0.92}
        stats = MagicMock()

        _update_thread_tracking_on_reingest(metadata, result, company, stats)

        spurious_tt.refresh_from_db()
        assert spurious_tt.rejection_date is None
        assert spurious_tt.cancelled is False

        application_tt.refresh_from_db()
        assert application_tt.rejection_date is not None
        assert application_tt.cancelled is True

    def test_reingest_cross_thread_finds_actual_application(
        self, company, application_tt, spurious_tt
    ):
        """During reingest, the function should ALSO update the actual application
        via TF-IDF fallback when the thread_id-matched TT has no job_title."""
        from parser import _update_thread_tracking_on_reingest

        metadata = self._make_metadata()
        result = {"label": "rejection", "confidence": 0.92}
        stats = MagicMock()

        with patch(
            "parser._find_and_update_rejection_by_company"
        ) as mock_find:
            _update_thread_tracking_on_reingest(metadata, result, company, stats)

            # Should attempt cross-thread TF-IDF match because spurious TT has no job_title
            mock_find.assert_called_once()
            call_args = mock_find.call_args
            assert call_args[0][1] == company  # company_obj

    def test_reingest_no_cross_thread_when_tt_has_job_title(
        self, company, db
    ):
        """If the TT found by thread_id has a job_title, no cross-thread fallback."""
        from parser import _update_thread_tracking_on_reingest

        # Create a TT with a real job_title
        real_tt = ThreadTracking.objects.create(
            thread_id="thread_real",
            company=company,
            company_source="domain_mapping",
            job_title="Real Position",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 10),
        )

        metadata = self._make_metadata(thread_id="thread_real")
        result = {"label": "rejection", "confidence": 0.92}
        stats = MagicMock()

        with patch(
            "parser._find_and_update_rejection_by_company"
        ) as mock_find:
            _update_thread_tracking_on_reingest(metadata, result, company, stats)

            # Should NOT attempt cross-thread match because TT has a job_title
            mock_find.assert_not_called()

        real_tt.refresh_from_db()
        assert real_tt.rejection_date is not None
        assert real_tt.cancelled is True  # body still has cancellation text

    def test_reingest_cancelled_label_sets_cancelled(self, company, spurious_tt):
        """ml_label='cancelled' should set cancelled=True regardless of body content."""
        from parser import _update_thread_tracking_on_reingest

        metadata = {
            "thread_id": "19c7b42504ee5c72",
            "timestamp": timezone.now(),
            "subject": "Position Update",
            "body": "No cancellation phrases here.",
        }
        result = {"label": "cancelled", "confidence": 0.95}
        stats = MagicMock()

        _update_thread_tracking_on_reingest(metadata, result, company, stats)

        spurious_tt.refresh_from_db()
        assert spurious_tt.rejection_date is not None
        assert spurious_tt.cancelled is True

    def test_reingest_no_tt_falls_through_to_tfidf(self, company, application_tt):
        """When no TT exists for the thread_id, should attempt TF-IDF match for rejections."""
        from parser import _update_thread_tracking_on_reingest

        metadata = self._make_metadata(thread_id="thread_nonexistent")
        result = {"label": "rejection", "confidence": 0.92}
        stats = MagicMock()

        with patch(
            "parser._find_and_update_rejection_by_company"
        ) as mock_find:
            _update_thread_tracking_on_reingest(metadata, result, company, stats)
            mock_find.assert_called_once()

    def test_reingest_withdrawal_does_not_reject_other_company_role(self, company):
        """Re-ingesting one role withdrawal must not reject another role at same company."""
        from parser import _update_thread_tracking_on_reingest

        placeholder_tt = ThreadTracking.objects.create(
            thread_id="thread_placeholder",
            company=company,
            company_source="domain_mapping",
            job_title="",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 20),
            ml_label="job_application",
        )
        withdrawn_role_tt = ThreadTracking.objects.create(
            thread_id="thread_real_withdrawn",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Information System Security Specialist",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 1),
            ml_label="job_application",
        )
        other_role_tt = ThreadTracking.objects.create(
            thread_id="thread_other_role",
            company=company,
            company_source="domain_mapping",
            job_title="Senior Cybersecurity Engineer",
            job_id="",
            status="application",
            sent_date=datetime.date(2026, 2, 2),
            ml_label="job_application",
        )

        metadata = {
            "thread_id": "thread_placeholder",
            "timestamp": timezone.now(),
            "subject": "Confirmation of withdraw from Senior Information System Security Specialist",
            "body": "You have successfully withdrawn from Senior Information System Security Specialist.",
        }
        result = {"label": "rejection", "confidence": 1.0}
        stats = MagicMock()

        _update_thread_tracking_on_reingest(metadata, result, company, stats)

        placeholder_tt.refresh_from_db()
        withdrawn_role_tt.refresh_from_db()
        other_role_tt.refresh_from_db()

        assert placeholder_tt.rejection_date is None
        assert withdrawn_role_tt.rejection_date is not None
        assert other_role_tt.rejection_date is None
