"""Tests for parser_helpers.py — extracted constants and helpers.

Tests cover:
- Phase 1: CANCELLED_PATTERNS and is_cancelled_position()
- Phase 2: _increment_stat()
- Phase 5: _is_headhunter_source()

These tests ensure the extracted helpers produce identical behavior
to the inline code they replaced.
"""

import re
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from parser_helpers import (
    CANCELLED_PATTERNS,
    is_cancelled_position,
    _increment_stat,
    _is_headhunter_source,
)


# =============================================================================
# Phase 1 tests: CANCELLED_PATTERNS and is_cancelled_position()
# =============================================================================


class TestCancelledPatterns:
    """Test CANCELLED_PATTERNS constant and is_cancelled_position helper."""

    def test_patterns_are_precompiled(self):
        """All patterns should be compiled regex objects."""
        assert len(CANCELLED_PATTERNS) == 8
        for p in CANCELLED_PATTERNS:
            assert isinstance(p, re.Pattern), f"Expected compiled regex, got {type(p)}"

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Pattern 1: decided/chosen not to fill
            ("We have decided not to fill this role at this time.", True),
            ("The team has chosen not to fill the position.", True),
            ("We decided not to move forward with filling this role.", True),
            # Pattern 2: evolving business needs
            ("Due to evolving business needs, we will not proceed.", True),
            ("Evolving business needs mean we cannot move forward.", False),  # 'cannot' ≠ 'not'
            # Pattern 3: not move forward with filling
            ("We will not move forward with filling this role.", True),
            ("We have decided not to move forward with filling the position.", True),
            # Pattern 4: close the position and not move forward (ARES email)
            (
                "it has been determined to close the Cybersecurity Program Manager "
                "position and not move forward with filing this role",
                True,
            ),
            ("We have decided to close the position and not move forward.", True),
            # Pattern 5: determined/decided to close
            ("It has been determined to close the position.", True),
            ("We have decided to close this role.", True),
            # Pattern 6: role/position has been closed/cancelled
            ("The position has been closed.", True),
            ("This role has been cancelled.", True),
            ("The position has been canceled.", True),
            ("The role was closed.", False),  # "was" not covered by "has been"
            ("The position closed.", True),  # 'has been' is optional in pattern 6
            # Pattern 7: not proceed with filing/filling
            ("We will not proceed with filling the position.", True),
            ("We decided not to move forward with filing this role.", True),
            # Pattern 8: literal cancelled/canceled
            ("This position has been cancelled.", True),
            ("The role was canceled.", True),
            ("closed/cancelled", True),
            ("cancelled/closed", True),
            # Negative cases
            ("Thank you for your application.", False),
            ("We are pleased to offer you the position.", False),
            ("Please schedule your interview.", False),
            ("", False),
        ],
    )
    def test_is_cancelled_position(self, text, expected):
        """is_cancelled_position should match known cancellation phrases."""
        result = is_cancelled_position("", text)
        assert result == expected, f"Expected {expected} for: {text!r}"

    def test_is_cancelled_position_subject_and_body(self):
        """Should check combined subject + body text."""
        # Pattern only in subject
        assert is_cancelled_position("Position cancelled", "Thank you") is True
        # Pattern only in body
        assert is_cancelled_position(
            "Update", "The role has been cancelled."
        ) is True
        # Neither
        assert is_cancelled_position("Hello", "World") is False

    def test_case_insensitive(self):
        """Patterns should match case-insensitively."""
        assert is_cancelled_position("", "POSITION HAS BEEN CANCELLED") is True
        assert is_cancelled_position("", "Position Has Been Cancelled") is True
        assert is_cancelled_position("", "position has been cancelled") is True


# =============================================================================
# Phase 2 tests: _increment_stat()
# =============================================================================


class TestIncrementStat:
    """Test _increment_stat helper."""

    @patch("parser_helpers.IngestionStats.objects")
    def test_increments_db_and_memory(self, mock_objects):
        """Should update both the DB (via F()) and the in-memory stats object."""
        from datetime import date

        stats = SimpleNamespace(date=date(2026, 2, 17), total_ignored=5)
        mock_filter = MagicMock()
        mock_objects.filter.return_value = mock_filter

        _increment_stat(stats, "total_ignored")

        # Verify DB update
        mock_objects.filter.assert_called_once_with(date=date(2026, 2, 17))
        mock_filter.update.assert_called_once()
        # Check that F expression was used (the kwarg key is 'total_ignored')
        call_kwargs = mock_filter.update.call_args[1]
        assert "total_ignored" in call_kwargs

        # Verify in-memory increment
        assert stats.total_ignored == 6

    @patch("parser_helpers.IngestionStats.objects")
    def test_increments_different_fields(self, mock_objects):
        """Should work with different stat field names."""
        from datetime import date

        mock_objects.filter.return_value = MagicMock()

        for field in ("total_ignored", "total_inserted", "total_skipped"):
            stats = SimpleNamespace(date=date(2026, 1, 1))
            setattr(stats, field, 0)
            _increment_stat(stats, field)
            assert getattr(stats, field) == 1

    @patch("parser_helpers.IngestionStats.objects")
    def test_handles_missing_field(self, mock_objects):
        """Should not crash if the field doesn't exist on the stats object."""
        from datetime import date

        mock_objects.filter.return_value = MagicMock()
        stats = SimpleNamespace(date=date(2026, 1, 1))
        # No total_inserted attribute
        _increment_stat(stats, "total_inserted")
        # Should not raise, field just doesn't get set


# =============================================================================
# Phase 5 tests: _is_headhunter_source()
# =============================================================================


class TestIsHeadhunterSource:
    """Test _is_headhunter_source helper."""

    HEADHUNTER_DOMAINS = {"kforce.com", "akkodis.com", "insight.com", "randstad.com"}

    def _make_company(self, name="TestCo", domain="testco.com", status="active"):
        """Create a mock company object."""
        return SimpleNamespace(name=name, domain=domain, status=status)

    def test_sender_in_headhunter_domains(self):
        """Should detect headhunter by sender domain."""
        assert _is_headhunter_source(
            "kforce.com", None, self.HEADHUNTER_DOMAINS
        ) is True

    def test_sender_not_in_headhunter_domains(self):
        """Should not flag non-headhunter sender domains."""
        assert _is_headhunter_source(
            "google.com", None, self.HEADHUNTER_DOMAINS
        ) is False

    def test_company_domain_endswith_headhunter(self):
        """Should detect headhunter by company domain suffix match."""
        company = self._make_company(domain="careers.kforce.com")
        assert _is_headhunter_source(
            "other.com", company, self.HEADHUNTER_DOMAINS
        ) is True

    def test_company_status_headhunter(self):
        """Should detect headhunter by company status field."""
        company = self._make_company(status="headhunter")
        assert _is_headhunter_source(
            "other.com", company, self.HEADHUNTER_DOMAINS
        ) is True

    def test_company_name_headhunter(self):
        """Should detect headhunter by company name 'Headhunter'."""
        company = self._make_company(name="Headhunter")
        assert _is_headhunter_source(
            "other.com", company, self.HEADHUNTER_DOMAINS
        ) is True

    def test_company_name_headhunter_case_insensitive(self):
        """Name check should be case-insensitive."""
        company = self._make_company(name="HEADHUNTER")
        assert _is_headhunter_source(
            "other.com", company, self.HEADHUNTER_DOMAINS
        ) is True

    def test_ml_label_head_hunter(self):
        """Should detect headhunter by ML label."""
        assert _is_headhunter_source(
            "other.com", None, self.HEADHUNTER_DOMAINS, ml_label="head_hunter"
        ) is True

    def test_ml_label_non_headhunter(self):
        """Should not flag non-headhunter ML labels."""
        assert _is_headhunter_source(
            "other.com", None, self.HEADHUNTER_DOMAINS, ml_label="job_application"
        ) is False

    def test_no_company_no_sender_match(self):
        """Should return False when nothing matches."""
        assert _is_headhunter_source(
            "google.com", None, self.HEADHUNTER_DOMAINS
        ) is False

    def test_empty_sender_domain(self):
        """Should handle empty sender domain gracefully."""
        assert _is_headhunter_source(
            "", None, self.HEADHUNTER_DOMAINS
        ) is False

    def test_company_with_none_domain(self):
        """Should handle company with None domain."""
        company = self._make_company(domain=None)
        assert _is_headhunter_source(
            "other.com", company, self.HEADHUNTER_DOMAINS
        ) is False

    def test_company_with_empty_domain(self):
        """Should handle company with empty domain."""
        company = self._make_company(domain="")
        assert _is_headhunter_source(
            "other.com", company, self.HEADHUNTER_DOMAINS
        ) is False

    def test_multiple_signals_combined(self):
        """Should detect when multiple signals are present."""
        company = self._make_company(
            name="Headhunter", domain="kforce.com", status="headhunter"
        )
        assert _is_headhunter_source(
            "kforce.com", company, self.HEADHUNTER_DOMAINS, ml_label="head_hunter"
        ) is True  # All signals match, result should still be True
