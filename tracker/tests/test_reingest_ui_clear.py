from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch
import json
from pathlib import Path

from tracker.models import Company, Message, ThreadTracking


class ReingestUITest(TestCase):
    def setUp(self):
        now = timezone.now()
        self.company = Company.objects.create(name="TestCo", domain="testco.com", first_contact=now, last_contact=now)
        self.user = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client = Client()
        self.client.force_login(self.user)

    def test_ui_reingest_clears_review_and_preserves_unreviewed(self):
        # Create a message marked as reviewed (user earlier reviewed)
        msg = Message.objects.create(
            subject="UI Reingest",
            sender="sender@testco.com",
            thread_id="T-UI-1",
            company=self.company,
            timestamp=timezone.now(),
            msg_id="G-UI-1",
            ml_label="job_application",
            reviewed=True,
        )

        # Ensure ThreadTracking exists for the thread and marked reviewed
        tt = ThreadTracking.objects.create(
            thread_id="T-UI-1",
            company=self.company,
            ml_label="job_application",
            reviewed=True,
            sent_date=timezone.now().date(),
        )

        url = reverse("label_messages")
        data = {
            "action": "reingest_selected",
            "selected_messages": [str(msg.id)],
        }

        # Patch both Gmail service and parser.ingest_message
        def fake_ingest(service, msg_id):
            m = Message.objects.get(msg_id=msg_id)
            m.ml_label = "interview_invite"
            m.confidence = 0.95
            m.save()
            return True

        with patch("gmail_auth.get_gmail_service", return_value=object()):
            with patch("parser.ingest_message", side_effect=fake_ingest):
                resp = self.client.post(url, data, follow=True)
                self.assertIn(resp.status_code, (200, 302))

        # Refresh and verify label updated and reviewed is False (UI cleared + suppression)
        msg.refresh_from_db()
        self.assertEqual(msg.ml_label, "interview_invite")
        self.assertFalse(msg.reviewed)

        # Check audit log contains an entry for this msg_id
        audit_path = Path("logs") / "clear_reviewed_audit.log"
        self.assertTrue(audit_path.exists(), "Audit log should exist")
        content = audit_path.read_text(encoding="utf-8")
        lines = [l for l in content.splitlines() if l.strip()]
        self.assertTrue(any('G-UI-1' in l or 'G-UI-1' in json.loads(l).get('msg_id', '') for l in lines))
