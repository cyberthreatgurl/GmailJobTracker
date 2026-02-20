#!/usr/bin/env python3
"""
Regression Tests: Rejection emails misclassified as applications.

Emails with subjects like "Application Status for ..." often contain body text
that clearly indicates a rejection (e.g., "will not be proceeding", "position
being no longer available"). The broad "application status" pattern was matching
before the rejection signals could be detected.

Fix: Combined rejection patterns + rejection_override into a single check that
runs before application patterns, and added missing rejection phrasings.

Run with: pytest tests/test_rejection_override_classification.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django
django.setup()

from parser import rule_label


class TestRejectionOverrideBeatsApplication:
    """Rejection signals in body must beat broad application-subject patterns."""

    def test_booz_allen_rejection_via_workday(self):
        """Real email: 'Application Status for ...' subject with clear rejection body."""
        subject = "Application Status for Cyber Threat Intelligence Analyst, Senior"
        body = (
            "Hi Adrian, We appreciate your interest in the Cyber Threat Intelligence "
            "Analyst, Senior position and desire to change the world with us. "
            "Due to the position being no longer available, we will not be proceeding "
            "with your application at this time. We encourage you to keep checking "
            "our careers site for job opportunities."
        )
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"

    def test_not_be_proceeding_with_application(self):
        """'will not be proceeding with your application' = rejection."""
        subject = "Application Update"
        body = "We will not be proceeding with your application at this time."
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"

    def test_position_being_no_longer_available(self):
        """'position being no longer available' = rejection."""
        subject = "Application Status for Software Engineer"
        body = "Due to the position being no longer available, we regret to inform you."
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"

    def test_position_is_no_longer_available(self):
        """'position is no longer available' = rejection (existing pattern)."""
        subject = "Update on your application"
        body = "The position is no longer available."
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"

    def test_not_proceeding_with_your_candidacy(self):
        """'not proceeding with your' = rejection."""
        subject = "Your Application Status"
        body = "After careful review, we are not proceeding with your candidacy."
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"

    def test_decided_not_to_proceed(self):
        """'decided not to proceed' = rejection (existing override pattern)."""
        subject = "Application Status for Data Analyst"
        body = "We have decided not to proceed with your application."
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"

    def test_moving_forward_with_other_candidates(self):
        """'moving forward with other candidates' = rejection."""
        subject = "Application Status"
        body = "We are moving forward with other candidates for this position."
        result = rule_label(subject, body)
        assert result == "rejection", f"Expected rejection, got {result}"


class TestApplicationStillWorks:
    """Application classification must still work for genuine confirmations."""

    def test_thank_you_for_applying(self):
        """Standard application confirmation still classified correctly."""
        subject = "Thank you for applying to Software Engineer at Acme"
        body = "We received your application and will review it carefully."
        result = rule_label(subject, body)
        assert result == "job_application", f"Expected job_application, got {result}"

    def test_application_submitted(self):
        """'application submitted' with no rejection language = application."""
        subject = "Your application has been submitted"
        body = "Your application for Data Scientist has been submitted successfully."
        result = rule_label(subject, body)
        assert result == "job_application", f"Expected job_application, got {result}"

    def test_application_received(self):
        """'application received' with no rejection language = application."""
        subject = "Application received"
        body = "We have received your application and will be in touch."
        result = rule_label(subject, body)
        assert result == "job_application", f"Expected job_application, got {result}"

    def test_application_status_no_rejection(self):
        """'application status' with neutral body = application."""
        subject = "Application Status for Cloud Engineer"
        body = "Your application for Cloud Engineer is under review."
        result = rule_label(subject, body)
        # This could be 'job_application' or 'other' (status_update) depending
        # on which patterns match. The key is it must NOT be 'rejection'.
        assert result != "rejection", f"Should not be rejection, got {result}"


class TestCancelledStillWorks:
    """Cancelled classification must still beat rejection."""

    def test_position_cancelled(self):
        """Explicit 'position has been cancelled' = cancelled, not rejection."""
        subject = "Position Update"
        body = "The position has been cancelled."
        result = rule_label(subject, body)
        assert result == "cancelled", f"Expected cancelled, got {result}"

    def test_role_closed(self):
        """'role has been closed' = cancelled."""
        subject = "Update on Software Engineer role"
        body = "The role has been closed and is no longer being filled."
        result = rule_label(subject, body)
        assert result == "cancelled", f"Expected cancelled, got {result}"
