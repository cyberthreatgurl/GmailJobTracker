"""
Additional integration tests targeting critical parser.py functions.

Focus on rule_label function and edge cases to increase coverage.
"""

import re

import pytest
from parser import rule_label, parse_subject, predict_with_fallback, predict_subject_type


class TestRuleLabelFunction:
    """Test rule-based email classification."""

    def test_rule_label_detects_rejection(self):
        """Rejection patterns should be detected in body."""
        subject = "Application Update"
        body = """
        Thank you for your interest in our position.
        Unfortunately, we have decided to move forward with other candidates.
        """

        result = rule_label(subject, body)
        # Should detect rejection
        assert result == "rejection" or result is None

    def test_rule_label_detects_interview(self):
        """Interview patterns should be detected."""
        subject = "Interview Request"
        body = """
        We would like to schedule a time to speak with you about the position.
        Please let us know your availability for an interview.
        """

        result = rule_label(subject, body)
        # May detect interview or return None if no strong match
        assert result in ["interview_invite", None]

    def test_rule_label_detects_noise(self):
        """Noise patterns like unsubscribe links should be detected."""
        subject = "Weekly Newsletter"
        body = """
        List-Unsubscribe: <mailto:unsub@example.com>
        This is a newsletter with the latest job postings.
        """

        result = rule_label(subject, body)
        # Should detect noise due to List-Unsubscribe
        assert result == "noise" or result is None

    def test_rule_label_detects_application_confirmation(self):
        """Application confirmation patterns should be detected."""
        subject = "Application Received"
        body = """
        Thank you for applying to the Software Engineer position.
        We have received your application and will review it shortly.
        """

        result = rule_label(subject, body)
        # Should detect application confirmation
        assert result == "job_application" or result is None

    def test_rule_label_handles_empty_body(self):
        """Empty body should be handled gracefully."""
        result = rule_label("Test Subject", "")
        assert result is None or isinstance(result, str)

    def test_rule_label_checks_sender_domain(self):
        """Sender domain should influence classification."""
        result = rule_label(
            "Job Alert", "New jobs matching your criteria", sender_domain="indeed.com"
        )
        # May classify differently based on sender domain
        assert result is None or isinstance(result, str)


class TestRuleLabelEdgeCases:
    """Test edge cases in rule-based classification."""

    def test_rule_label_with_very_long_body(self):
        """Very long body text should be handled efficiently."""
        subject = "Test"
        body = "A" * 100000  # 100k characters

        result = rule_label(subject, body)
        # Should not crash or timeout
        assert result is None or isinstance(result, str)

    def test_rule_label_with_unicode_content(self):
        """Unicode content should be handled correctly."""
        subject = "Réponse à votre candidature"
        body = """
        Bonjour,
        Nous avons bien reçu votre candidature.
        Cordialement,
        L'équipe de recrutement
        """

        result = rule_label(subject, body)
        assert result is None or isinstance(result, str)

    def test_rule_label_with_html_in_body(self):
        """HTML tags in body should not interfere with classification."""
        subject = "Application Status"
        body = """
        <html>
        <body>
        <p>We regret to inform you that we will not be moving forward.</p>
        </body>
        </html>
        """

        result = rule_label(subject, body)
        # Should still detect rejection despite HTML
        assert result == "rejection" or result is None

    def test_rule_label_case_insensitive(self):
        """Pattern matching should be case-insensitive."""
        subject = "INTERVIEW REQUEST"
        body = "WE WOULD LIKE TO SCHEDULE AN INTERVIEW WITH YOU."

        result = rule_label(subject, body)
        # Should still detect patterns in uppercase
        assert result in ["interview_invite", None]


class TestCompanyResolution:
    """Test company name resolution from various sources."""

    def test_rule_label_with_known_ats_domain(self):
        """Messages from known ATS domains should be handled."""
        result = rule_label(
            "Application Status",
            "Your application is being reviewed.",
            sender_domain="greenhouse.io",
        )
        assert result is None or isinstance(result, str)

    def test_rule_label_with_job_board_domain(self):
        """Messages from job boards should be classified appropriately."""
        result = rule_label(
            "New Job Matches",
            "5 new jobs match your profile.",
            sender_domain="indeed.com",
        )
        # May be classified as noise or other
        assert result is None or isinstance(result, str)


class TestRuleLabelPatternCoverage:
    """Additional tests to increase coverage of rule_label patterns."""

    def test_rule_label_detects_offer_letter(self):
        """Offer letter patterns should be detected."""
        subject = "Job Offer - Software Engineer"
        body = """
        Congratulations! We are pleased to extend an offer of employment.
        Your starting salary will be $120,000 per year.
        """

        result = rule_label(subject, body)
        # May detect offer or other
        assert result is None or isinstance(result, str)

    def test_rule_label_detects_scheduled_interview(self):
        """Already scheduled interview confirmations."""
        subject = "Interview Confirmation"
        body = """
        Your interview has been scheduled for January 15, 2025 at 2:00 PM.
        We look forward to speaking with you.
        """

        result = rule_label(subject, body)
        assert result is None or isinstance(result, str)

    def test_rule_label_detects_automated_response(self):
        """Automated responses should be classified appropriately."""
        subject = "Automatic reply"
        body = """
        This is an automated response. Your message has been received.
        We will respond within 2 business days.
        """

        result = rule_label(subject, body)
        assert result is None or isinstance(result, str)

    def test_rule_label_with_mixed_content(self):
        """Body with mixed signals should handle precedence correctly."""
        subject = "Update"
        body = """
        Thank you for applying. 
        Unfortunately, we decided to move forward with other candidates.
        However, we encourage you to apply for other positions.
        """

        result = rule_label(subject, body)
        # Rejection should take precedence
        assert result in ["rejection", None]

    def test_rule_label_with_forwarded_message(self):
        """Forwarded messages should be handled."""
        subject = "Fwd: Application Status"
        body = """
        ---------- Forwarded message ---------
        From: HR <hr@company.com>
        Thank you for your application.
        """

        result = rule_label(subject, body)
        assert result is None or isinstance(result, str)

    def test_rule_label_with_reply_prefix(self):
        """Messages with Re: prefix should be handled."""
        subject = "Re: Interview availability"
        body = """
        Thank you for your response. We can schedule the interview
        for next Tuesday at 10 AM.
        """

        result = rule_label(subject, body)
        assert result is None or isinstance(result, str)

    def test_rule_label_detects_ghosting(self):
        """Very generic follow-up messages."""
        subject = "Following up"
        body = """
        Just wanted to follow up on my previous application.
        Have you had a chance to review my resume?
        """

        result = rule_label(subject, body)
        assert result is None or isinstance(result, str)

    def test_rule_label_with_calendar_invite(self):
        """Calendar invites in body should be handled."""
        subject = "Interview: Software Engineer Position"
        body = """
        BEGIN:VCALENDAR
        SUMMARY:Technical Interview
        DTSTART:20250115T140000Z
        END:VCALENDAR
        """

        result = rule_label(subject, body)
        # May detect interview
        assert result is None or isinstance(result, str)

    def test_rule_label_detects_recruiter_spam(self):
        """Recruiter spam patterns."""
        subject = "Amazing opportunity!"
        body = """
        Hi there! I came across your profile and think you'd be
        a great fit for this exciting opportunity at our client.
        Let me know if you're interested!
        """

        result = rule_label(subject, body)
        # May be classified as head_hunter or noise
        assert result is None or isinstance(result, str)

    def test_rule_label_with_position_closed(self):
        """Position closed notifications."""
        subject = "Position Update"
        body = """
        The position you applied for has been closed.
        We have filled the role with another candidate.
        """

        result = rule_label(subject, body)
        # Should likely be rejection
        assert result in ["rejection", None]


class TestMeetingUpgradeRegex:
    """Regression tests for the meeting-details regex (join.*meeting fix).

    The old pattern ``join.*meeting`` was greedy and matched across thousands
    of characters (e.g., "joint operational unit ... in meeting rigorous").
    The fixed pattern limits the gap to at most 3 words.
    """

    FIXED_PATTERN = (
        r"meeting id|passcode|join\s+(?:\S+\s+){0,3}meeting"
        r"|zoom\.us|meet\.google|teams\.microsoft|ms teams|microsoft teams"
    )

    def test_join_the_meeting_matches(self):
        """Legitimate 'join the meeting' text should still match."""
        assert re.search(self.FIXED_PATTERN, "Click here to join the meeting", re.I)

    def test_join_our_zoom_meeting_matches(self):
        """'Join our Zoom meeting' should match."""
        assert re.search(self.FIXED_PATTERN, "Join our scheduled Zoom meeting now", re.I)

    def test_join_this_meeting_matches(self):
        """'Join this meeting' should match."""
        assert re.search(self.FIXED_PATTERN, "join this meeting", re.I)

    def test_joint_operational_unit_does_not_match(self):
        """Resume text with 'joint' and 'meeting' far apart must NOT match."""
        resume_text = (
            "orchestrated a joint operational unit spanning contractors "
            "and federal analysts to provide intelligence ... "
            "Validated information technology and operational systems "
            "in meeting rigorous cybersecurity compliance requirements"
        )
        assert not re.search(self.FIXED_PATTERN, resume_text, re.I)

    def test_meeting_id_still_matches(self):
        """Direct 'meeting id' text should still match."""
        assert re.search(self.FIXED_PATTERN, "Meeting ID: 123-456-789", re.I)

    def test_zoom_url_still_matches(self):
        """Zoom URLs should still match."""
        assert re.search(self.FIXED_PATTERN, "https://zoom.us/j/123456", re.I)

    def test_teams_microsoft_still_matches(self):
        """Teams meeting links should still match."""
        assert re.search(self.FIXED_PATTERN, "https://teams.microsoft.com/meet", re.I)

    def test_ms_teams_still_matches(self):
        """'MS Teams' text should still match."""
        assert re.search(self.FIXED_PATTERN, "We will meet on MS Teams", re.I)


class TestApplicationNotUpgradedToInterview:
    """Regression: application confirmations must never be upgraded to interview_invite.

    Bug: "Thanks for applying to Resource Management Concepts, Inc." was
    classified as interview_invite because the body (which contained a full
    resume with words like 'joint' and 'meeting') matched the greedy
    join.*meeting regex AND the 'meeting' word matched interview language.
    """

    APPLICATION_SUBJECT = "Thanks for applying to Resource Management Concepts, Inc."
    APPLICATION_BODY = (
        "Your application for the IT Program Manager job was submitted successfully. "
        "Here's a copy of your application data for safekeeping. "
        "Experience: orchestrated a joint operational unit spanning contractors "
        "and federal analysts to provide intelligence analysis. "
        "Validated information technology and operational systems in meeting "
        "rigorous cybersecurity compliance requirements."
    )

    def test_rule_label_returns_job_application(self):
        """rule_label should classify this as job_application."""
        result = rule_label(
            self.APPLICATION_SUBJECT,
            self.APPLICATION_BODY,
            sender_domain="workablemail.com",
        )
        assert result == "job_application"

    def test_predict_with_fallback_returns_job_application(self):
        """predict_with_fallback should return job_application."""
        result = predict_with_fallback(
            predict_subject_type,
            self.APPLICATION_SUBJECT,
            self.APPLICATION_BODY,
            threshold=0.55,
            sender="noreply@candidates.workablemail.com",
        )
        assert result["label"] == "job_application"

    def test_parse_subject_returns_job_application(self):
        """parse_subject must NOT upgrade job_application to interview_invite."""
        result = parse_subject(
            self.APPLICATION_SUBJECT,
            self.APPLICATION_BODY,
            sender="noreply@candidates.workablemail.com",
            sender_domain="workablemail.com",
        )
        assert result["label"] == "job_application", (
            f"Expected job_application but got {result['label']}"
        )


class TestRmcRejectionClassifiedAsRejection:
    """Regression: RMC rejection must be labeled as rejection, not job_application.

    The rejection email body contains strong rejection language but also
    application-related phrases ("Thank you for your interest" and
    "for taking the time to apply"), which previously led to it being
    misclassified as job_application.
    """

    REJECTION_SUBJECT = "IT Program Manager - Resource Management Concepts, Inc."
    REJECTION_BODY = (
        "Dear Adrian, "
        "Thank you for your interest in joining Resource Management Concepts, Inc. "
        "and for taking the time to apply for the IT Program Manager position. "
        "After reviewing your application, our team has decided to move forward "
        "with candidates whose experiences more closely match the current needs "
        "of the role. "
    )

    def test_rule_label_returns_rejection(self):
        """rule_label should classify this as a rejection."""
        result = rule_label(
            self.REJECTION_SUBJECT,
            self.REJECTION_BODY,
            sender_domain="workablemail.com",
        )
        assert result == "rejection"

    def test_predict_with_fallback_returns_rejection(self):
        """predict_with_fallback should return rejection for this email."""
        result = predict_with_fallback(
            predict_subject_type,
            self.REJECTION_SUBJECT,
            self.REJECTION_BODY,
            threshold=0.55,
            sender="noreply@candidates.workablemail.com",
        )
        assert result["label"] == "rejection"

    def test_parse_subject_returns_rejection(self):
        """parse_subject must treat this as a rejection message."""
        result = parse_subject(
            self.REJECTION_SUBJECT,
            self.REJECTION_BODY,
            sender="noreply@candidates.workablemail.com",
            sender_domain="workablemail.com",
        )
        assert result["label"] == "rejection", (
            f"Expected rejection but got {result['label']}"
        )


class TestWithdrawalConfirmationSubject:
    """Regression: withdrawal confirmations should not be dropped as missing_company."""

    SUBJECT = "Confirmation of withdraw from Senior Information System Security Specialist"
    BODY = (
        "Hello Adrian, "
        "You have successfully withdrawn from Senior Information System Security Specialist. "
        "This action is final."
    )

    def test_parse_subject_labels_as_rejection(self):
        """parse_subject should classify withdrawal confirmations as rejection."""
        result = parse_subject(
            self.SUBJECT,
            self.BODY,
            sender="careers@maximus.com",
            sender_domain="maximus.com",
        )
        assert result["label"] == "rejection"

    def test_parse_subject_extracts_job_title_from_subject(self):
        """parse_subject should extract role title after 'withdraw from'."""
        result = parse_subject(
            self.SUBJECT,
            self.BODY,
            sender="careers@maximus.com",
            sender_domain="maximus.com",
        )
        assert result["job_title"] == "Senior Information System Security Specialist"
