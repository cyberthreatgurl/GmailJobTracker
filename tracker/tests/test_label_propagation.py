from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib import admin
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.management import call_command
from unittest.mock import patch

from tracker.models import Company, Message, ThreadTracking
from tracker.admin import MessageAdmin, custom_admin_site


class LabelPropagationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.company = Company.objects.create(name="TestCo", domain="testco.com", first_contact=now, last_contact=now)
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
        msg = Message.objects.create(
            subject="Mgmt Reclassify",
            sender="x@testco.com",
            thread_id="T-MGMT-1",
            company=self.company,
            timestamp=timezone.now(),
            ml_label=None,
            confidence=0.1,
        )

        # Patch the predict function used by the management command to return a deterministic label
        with patch("tracker.management.commands.reclassify_messages.predict_subject_type", return_value={
            "label": "job_application",
            "confidence": 0.95,
            "method": "test",
        }):
            call_command("reclassify_messages", "--limit", "1")

        tt = ThreadTracking.objects.filter(thread_id="T-MGMT-1").first()
        self.assertIsNotNone(tt, "ThreadTracking should be created by reclassify management command")
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
