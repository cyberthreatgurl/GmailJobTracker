from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from tracker.views.companies import _scrape_job_posting_content


class JobPostingScrapeHelperTests(TestCase):
    @patch("tracker.views.companies.fetch_rendered_page")
    @patch("tracker.views.companies.fetch_best_effort_page")
    def test_scrape_job_posting_content_uses_rendered_fallback_for_shell_page(self, mock_best_effort, mock_rendered):
        url = "https://talent.spa.com/jobs/123"
        mock_best_effort.return_value = {
            "success": True,
            "source_method": "static",
            "final_url": url,
            "status_code": 200,
            "html": "<html><body>shell</body></html>",
            "text": "shell",
            "captured_json": [],
            "error": None,
        }
        mock_rendered.return_value = {
            "success": True,
            "source_method": "rendered",
            "final_url": url,
            "status_code": 200,
            "html": (
                "<main>"
                "<h1>Open Source Intelligence Analyst</h1>"
                "<p>Location Quantico, Virginia US Categories Program &amp; Project Management</p>"
                "<p>This role supports mission analysis, reporting, and field operations.</p>"
                "</main>"
            ),
            "text": "Open Source Intelligence Analyst Location Quantico, Virginia US",
            "captured_json": [],
            "error": None,
        }

        result = _scrape_job_posting_content(url)

        self.assertTrue(result["success"])
        self.assertEqual(result["source_method"], "rendered")
        self.assertEqual(result["extracted_location"], "Quantico, VA")
        self.assertIn("Open Source Intelligence Analyst", result["content"])


class JobPostingScrapeViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="jobuser", password="testpass")
        self.client.login(username="jobuser", password="testpass")

    @patch("tracker.views.companies.fetch_rendered_page")
    @patch("tracker.views.companies.fetch_best_effort_page")
    def test_scrape_job_posting_view_returns_user_friendly_error_when_rendering_still_fails(self, mock_best_effort, mock_rendered):
        url = "https://talent.spa.com/jobs/456"
        mock_best_effort.return_value = {
            "success": True,
            "source_method": "static",
            "final_url": url,
            "status_code": 200,
            "html": "<html><body>shell</body></html>",
            "text": "shell",
            "captured_json": [],
            "error": None,
        }
        mock_rendered.return_value = {
            "success": False,
            "source_method": "rendered",
            "final_url": url,
            "status_code": None,
            "html": "",
            "text": "",
            "captured_json": [],
            "error": "Rendered page fetch failed: browser unavailable",
        }

        response = self.client.post("/api/scrape_job_posting/", {"url": url})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("JavaScript to load content", data["error"])

    @patch("tracker.views.companies.fetch_best_effort_page")
    def test_extract_company_locations_uses_captured_json_fallback(self, mock_best_effort):
        url = "https://talent.spa.com/jobs?page=1"
        mock_best_effort.return_value = {
            "success": True,
            "source_method": "rendered",
            "final_url": url,
            "status_code": 200,
            "html": "<html><body><div id='app'></div></body></html>",
            "text": "Systems Planning and Analysis job search",
            "captured_json": [
                {
                    "url": "https://talent.spa.com/api/jobs?page=1",
                    "data": {
                        "locations": ["Shiloh, VA 22485, USA"],
                        "jobs": [
                            {"data": {"city": "Quantico", "state": "Virginia", "country": "United States"}},
                            {"data": {"city": "Springfield", "state": "Virginia", "country": "United States"}},
                        ],
                    },
                }
            ],
            "error": None,
        }

        response = self.client.post("/api/extract_locations/", {"url": url})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("Quantico, VA", data["locations"])
        self.assertIn("Springfield, VA", data["locations"])