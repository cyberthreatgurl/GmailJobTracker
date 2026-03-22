from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.management import call_command
from unittest.mock import patch

from tracker.models import Company, Message, ThreadTracking
from tracker.admin import MessageAdmin, custom_admin_site


class LabelPropagationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.company = Company.objects.create(
            name="TestCo", domain="testco.com", first_contact=now, last_contact=now
        )
        self.user = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client = Client()
        self.client.force_login(self.user)
        self.factory = RequestFactory()

    def test_admin_save_propagates(self):
        # Create an initial message (simulate existing DB row)
        msg = Message.objects.create(
            subject="Admin Propagate",
            sender="sender@testco.com",
            thread_id="T-ADMIN-1",
            company=self.company,
            timestamp=timezone.now(),
        )

        # Now simulate admin editing the message's ml_label
        msg.ml_label = "job_application"
        admin_instance = MessageAdmin(Message, custom_admin_site)
        req = self.factory.post("/")
        req.user = self.user

        # Save via admin.save_model (should create ThreadTracking)
        admin_instance.save_model(req, msg, form=None, change=True)

        tt = ThreadTracking.objects.filter(thread_id="T-ADMIN-1").first()
        self.assertIsNotNone(tt, "ThreadTracking should be created by admin save")
        self.assertEqual(tt.ml_label, "job_application")

    def test_management_command_reclassify_propagates(self):
        # Create a message to be reclassified
        Message.objects.create(
            subject="Mgmt Reclassify",
            sender="x@testco.com",
            thread_id="T-MGMT-1",
            company=self.company,
            timestamp=timezone.now(),
            ml_label=None,
            confidence=0.1,
        )

        # Patch the predict function used by the management command to return a deterministic label
        with patch(
            "tracker.management.commands.reclassify_messages.predict_subject_type",
            return_value={
                "label": "job_application",
                "confidence": 0.95,
                "method": "test",
            },
        ):
            call_command("reclassify_messages", "--limit", "1")

        tt = ThreadTracking.objects.filter(thread_id="T-MGMT-1").first()
        self.assertIsNotNone(
            tt, "ThreadTracking should be created by reclassify management command"
        )
        self.assertEqual(tt.ml_label, "job_application")

    def test_bulk_label_view_propagates(self):
        # Create message to be labeled via the bulk UI
        msg = Message.objects.create(
            subject="Bulk Label",
            sender="bulk@testco.com",
            thread_id="T-BULK-1",
            company=self.company,
            timestamp=timezone.now(),
        )

        url = reverse("label_messages")
        data = {
            "action": "bulk_label",
            "selected_messages": [str(msg.id)],
            "bulk_label": "job_application",
        }
        resp = self.client.post(url, data, follow=True)
        self.assertIn(resp.status_code, (200, 302))

        tt = ThreadTracking.objects.filter(thread_id="T-BULK-1").first()
        self.assertIsNotNone(tt, "ThreadTracking should be created by bulk label view")
        self.assertEqual(tt.ml_label, "job_application")

    def test_orphan_prescreen_does_not_attach_to_unrelated_application(self):
        msg = Message.objects.create(
            subject="Phone screen availability",
            sender="Recruiter <recruiter@testco.com>",
            thread_id="T-OLD-PRESCREEN",
            msg_id="M-OLD-PRESCREEN",
            company=self.company,
            company_source="manual",
            body="Would you be available for a phone screen next week?",
            timestamp=timezone.now().replace(year=timezone.now().year - 1),
            ml_label="prescreen",
            confidence=0.99,
        )
        existing_tt = ThreadTracking.objects.create(
            thread_id="T-CURRENT-APP",
            company=self.company,
            company_source="manual",
            job_title="Security Engineer",
            job_id="REQ-1",
            status="application",
            sent_date=timezone.now().date(),
            ml_label="job_application",
            ml_confidence=0.95,
        )

        from tracker.utils.label_propagation import propagate_message_label_to_thread

        result = propagate_message_label_to_thread(msg)

        self.assertIsNone(result)
        existing_tt.refresh_from_db()
        self.assertIsNone(existing_tt.prescreen_date)
        self.assertEqual(ThreadTracking.objects.count(), 1)

    def test_prescreen_does_not_attach_to_future_application_with_matching_identity(self):
        msg = Message.objects.create(
            subject="Cyber Security Project Manager phone screen",
            sender="Recruiter <recruiter@testco.com>",
            thread_id="T-PRESCREEN-BEFORE-APP",
            msg_id="M-PRESCREEN-BEFORE-APP",
            company=self.company,
            company_source="manual",
            body="Let's schedule a phone screen for Cyber Security Project Manager (REQ-777).",
            timestamp=timezone.make_aware(timezone.datetime(2025, 10, 24, 12, 0, 0)),
            ml_label="prescreen",
            confidence=0.99,
        )
        future_tt = ThreadTracking.objects.create(
            thread_id="T-FUTURE-APP",
            company=self.company,
            company_source="manual",
            job_title="Cyber Security Project Manager",
            job_id="REQ-777",
            status="application",
            sent_date=timezone.datetime(2025, 11, 2).date(),
            ml_label="job_application",
            ml_confidence=0.95,
        )

        from tracker.utils.label_propagation import propagate_message_label_to_thread

        result = propagate_message_label_to_thread(msg)

        self.assertIsNone(result)
        future_tt.refresh_from_db()
        self.assertIsNone(future_tt.prescreen_date)
        self.assertEqual(ThreadTracking.objects.count(), 1)

    def test_offer_updates_associated_application_not_interview_thread(self):
        application_tt = ThreadTracking.objects.create(
            thread_id="T-APPLICATION",
            company=self.company,
            company_source="manual",
            job_title="Cyber Security Project Manager",
            job_id="",
            status="application",
            sent_date=timezone.datetime(2025, 11, 2).date(),
            ml_label="job_application",
            ml_confidence=0.95,
        )
        interview_tt = ThreadTracking.objects.create(
            thread_id="T-OFFER-THREAD",
            company=self.company,
            company_source="manual",
            job_title="",
            job_id="",
            status="ghosted",
            sent_date=timezone.datetime(2025, 11, 7).date(),
            ml_label="interview_invite",
            ml_confidence=0.95,
        )
        msg = Message.objects.create(
            subject="Let's Talk - Endyna",
            sender="recruiter@testco.com",
            thread_id="T-OFFER-THREAD",
            msg_id="M-OFFER-THREAD",
            company=self.company,
            company_source="manual",
            body="Thank you for interviewing with our CEO about the Cyber Security Project Manager position.",
            timestamp=timezone.make_aware(timezone.datetime(2025, 11, 7, 12, 0, 0)),
            ml_label="offer",
            confidence=0.99,
        )

        from tracker.utils.label_propagation import propagate_message_label_to_thread

        result = propagate_message_label_to_thread(msg)

        application_tt.refresh_from_db()
        interview_tt.refresh_from_db()
        self.assertEqual(result.id, application_tt.id)
        self.assertEqual(application_tt.offer_date, timezone.datetime(2025, 11, 7).date())
        self.assertEqual(application_tt.status, "offer")
        self.assertIsNone(interview_tt.offer_date)

    def test_compliance_prescreen_attaches_to_unique_active_application(self):
        active_tt = ThreadTracking.objects.create(
            thread_id="T-ACTIVE-APP",
            company=self.company,
            company_source="manual",
            job_title="Senior Cybersecurity Engineer",
            job_id="",
            status="application",
            sent_date=timezone.datetime(2026, 2, 20).date(),
            ml_label="job_application",
            ml_confidence=0.95,
        )
        ThreadTracking.objects.create(
            thread_id="T-WITHDRAWN-APP",
            company=self.company,
            company_source="manual",
            job_title="Senior Information System Security Specialist",
            job_id="",
            status="rejected",
            sent_date=timezone.datetime(2026, 2, 20).date(),
            rejection_date=timezone.datetime(2026, 2, 22).date(),
            withdrew=True,
            ml_label="job_application",
            ml_confidence=0.95,
        )
        msg = Message.objects.create(
            subject="[Compliance] You've been asked to complete a form",
            sender="noreply@threatswitch.com",
            thread_id="T-COMPLIANCE-PRESCREEN",
            msg_id="M-COMPLIANCE-PRESCREEN",
            company=self.company,
            company_source="manual",
            body="Your security manager has requested that you complete the form, Maximus Federal Services Pre-screen 2025.",
            timestamp=timezone.make_aware(timezone.datetime(2026, 2, 24, 16, 57, 6)),
            ml_label="prescreen",
            confidence=0.99,
        )

        from tracker.utils.label_propagation import propagate_message_label_to_thread

        result = propagate_message_label_to_thread(msg)

        active_tt.refresh_from_db()
        self.assertEqual(result.id, active_tt.id)
        self.assertEqual(active_tt.prescreen_date, timezone.datetime(2026, 2, 24).date())
