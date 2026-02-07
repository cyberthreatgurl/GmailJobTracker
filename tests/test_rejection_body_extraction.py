"""Tests for extracting job titles from rejection email bodies and matching to applications.

Covers the fix for rejections where the subject line contains no job title
(e.g., "A career opportunity with ECS Federal, LLC") but the body contains
the actual job title (e.g., "the position of Cybersecurity SME has been filled").
"""

import pytest

from parser import extract_job_title_from_body, find_best_matching_application

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Unit tests for extract_job_title_from_body
# ---------------------------------------------------------------------------


class TestExtractJobTitleFromBody:
    """Test regex-based job title extraction from rejection body text."""

    def test_position_of_filled(self):
        """'the position of X has been filled' pattern."""
        body = (
            "<P>We wanted to inform you that the position of&nbsp;"
            "Cybersecurity SME - Continuous Diagnostics and Mitigation"
            "&nbsp;has been filled by another candidate.</P>"
        )
        assert extract_job_title_from_body(body) == (
            "Cybersecurity SME - Continuous Diagnostics and Mitigation"
        )

    def test_position_of_closed(self):
        """'the position of X has been closed' pattern."""
        body = "Unfortunately, the position of Senior Data Analyst has been closed."
        assert extract_job_title_from_body(body) == "Senior Data Analyst"

    def test_position_has_been_filled(self):
        """'position of X has been filled' without 'the'."""
        body = "The position of Cloud Engineer has been filled by another candidate."
        assert extract_job_title_from_body(body) == "Cloud Engineer"

    def test_req_number_with_title(self):
        """'Req #1234-Title' ATS pattern."""
        body = (
            "<P>Re:&nbsp; Req #2890-Cybersecurity SME - CDM</P>"
            "<P>Dear Applicant:</P>"
        )
        assert extract_job_title_from_body(body) == "Cybersecurity SME - CDM"

    def test_regarding_position(self):
        """'regarding the X position' pattern."""
        body = "We are writing regarding the Software Engineer III position."
        assert extract_job_title_from_body(body) == "Software Engineer III"

    def test_regarding_role(self):
        """'regarding the X role' pattern."""
        body = "Thank you for your interest regarding the DevOps Lead role at Acme."
        assert extract_job_title_from_body(body) == "DevOps Lead"

    def test_application_for(self):
        """'your application for X has' pattern."""
        body = "Your application for Network Security Analyst has been reviewed."
        assert extract_job_title_from_body(body) == "Network Security Analyst"

    def test_applied_for_position(self):
        """'applied for X position' pattern."""
        body = "Thank you for having applied for Systems Administrator position."
        assert extract_job_title_from_body(body) == "Systems Administrator"

    def test_empty_body(self):
        """Empty body returns empty string."""
        assert extract_job_title_from_body("") == ""
        assert extract_job_title_from_body(None) == ""

    def test_no_patterns_match(self):
        """Body with no recognizable patterns returns empty string."""
        body = "Thank you for your interest. Unfortunately we cannot proceed."
        assert extract_job_title_from_body(body) == ""

    def test_html_entities_cleaned(self):
        """HTML &nbsp; entities are properly cleaned before matching."""
        body = "the position of&nbsp;Lead Analyst&nbsp;has been filled"
        assert extract_job_title_from_body(body) == "Lead Analyst"

    def test_html_tags_stripped(self):
        """HTML tags are stripped before matching."""
        body = "<p>the position of <b>Security Engineer</b> has been filled</p>"
        assert extract_job_title_from_body(body) == "Security Engineer"

    def test_for_the_opening(self):
        """'for the X opening' pattern."""
        body = "We appreciate your interest for the CISO opening at our company."
        assert extract_job_title_from_body(body) == "CISO"


# ---------------------------------------------------------------------------
# Integration tests: body extraction → TF-IDF matching → ThreadTracking update
# ---------------------------------------------------------------------------


class TestRejectionBodyToThreadTracking:
    """Test that rejection body job title extraction feeds into TF-IDF matching."""

    def test_body_title_matches_application(self, db):
        """Rejection with body-only job title should match existing application via TF-IDF."""
        from tracker.models import Company, ThreadTracking

        company = Company.objects.create(name="TestCorp", first_contact="2025-01-01", last_contact="2025-01-01")
        ThreadTracking.objects.create(
            thread_id="app_thread_1",
            company=company,
            status="application",
            job_title="Lead Cybersecurity SME",
            sent_date="2025-12-10",
        )

        # Simulate: subject has no title, body has "position of X has been filled"
        body = (
            "We wanted to inform you that the position of "
            "Cybersecurity SME - Continuous Diagnostics and Mitigation "
            "has been filled by another candidate."
        )
        body_title = extract_job_title_from_body(body)
        assert body_title == "Cybersecurity SME - Continuous Diagnostics and Mitigation"

        matched_tt = find_best_matching_application(
            company, body_title, "A career opportunity with TestCorp"
        )
        assert matched_tt is not None
        assert matched_tt.job_title == "Lead Cybersecurity SME"

    def test_body_title_with_multiple_applications(self, db):
        """When multiple applications exist, body title matches the correct one."""
        from tracker.models import Company, ThreadTracking

        company = Company.objects.create(name="TestCorp2", first_contact="2025-01-01", last_contact="2025-01-01")
        ThreadTracking.objects.create(
            thread_id="app_a",
            company=company,
            status="application",
            job_title="Data Analyst",
            sent_date="2025-11-01",
        )
        ThreadTracking.objects.create(
            thread_id="app_b",
            company=company,
            status="application",
            job_title="Senior Security Engineer",
            sent_date="2025-12-01",
        )

        body = "the position of Security Engineer has been filled."
        body_title = extract_job_title_from_body(body)
        matched = find_best_matching_application(
            company, body_title, "A career opportunity"
        )
        assert matched is not None
        assert matched.job_title == "Senior Security Engineer"

    def test_fallback_to_subject_when_body_empty(self, db):
        """When body has no extractable title, subject is used as fallback."""
        from tracker.models import Company, ThreadTracking

        company = Company.objects.create(name="TestCorp3", first_contact="2025-01-01", last_contact="2025-01-01")
        ThreadTracking.objects.create(
            thread_id="app_c",
            company=company,
            status="application",
            job_title="Python Developer",
            sent_date="2025-12-01",
        )

        # No recognizable pattern in body
        body_title = extract_job_title_from_body("Thank you for your interest.")
        assert body_title == ""

        # find_best_matching_application still works via subject fallback
        matched = find_best_matching_application(
            company, "", "Python Developer opportunity"
        )
        assert matched is not None
        assert matched.job_title == "Python Developer"
