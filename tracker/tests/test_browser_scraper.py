from unittest import TestCase
from unittest.mock import patch

from tracker.services.browser_scraper import (
    fetch_best_effort_page,
    should_fallback_to_browser,
    should_use_browser_first,
)
from tracker.services.company_scraper import scrape_company_info


class BrowserScraperHeuristicsTests(TestCase):
    def test_should_use_browser_first_for_known_ats_hosts(self):
        self.assertTrue(should_use_browser_first("https://talent.spa.com/jobs"))
        self.assertTrue(should_use_browser_first("https://boards.greenhouse.io/example/jobs/1"))
        self.assertFalse(should_use_browser_first("https://example.com/jobs"))

    def test_should_fallback_to_browser_for_low_signal_static_content(self):
        self.assertTrue(should_fallback_to_browser("https://example.com/jobs", "shell"))
        self.assertTrue(should_fallback_to_browser("https://example.com/jobs", "Access denied", 403))
        self.assertFalse(
            should_fallback_to_browser(
                "https://example.com/jobs",
                "Senior engineer role with responsibilities, qualifications, benefits, and team details " * 4,
                200,
            )
        )


class BrowserScraperFlowTests(TestCase):
    @patch("tracker.services.browser_scraper.fetch_rendered_page")
    @patch("tracker.services.browser_scraper.fetch_static_page")
    def test_fetch_best_effort_prefers_static_when_content_is_strong(self, mock_static, mock_rendered):
        mock_static.return_value = {
            "success": True,
            "source_method": "static",
            "final_url": "https://example.com/jobs/1",
            "status_code": 200,
            "html": "<main><p>" + ("Useful content " * 40) + "</p></main>",
            "text": "Useful content " * 40,
            "captured_json": [],
            "error": None,
        }

        result = fetch_best_effort_page("https://example.com/jobs/1")

        self.assertTrue(result["success"])
        self.assertEqual(result["source_method"], "static")
        mock_rendered.assert_not_called()

    @patch("tracker.services.browser_scraper.fetch_rendered_page")
    @patch("tracker.services.browser_scraper.fetch_static_page")
    def test_fetch_best_effort_uses_rendered_fallback_for_low_signal_static_content(self, mock_static, mock_rendered):
        mock_static.return_value = {
            "success": True,
            "source_method": "static",
            "final_url": "https://example.com/jobs/1",
            "status_code": 200,
            "html": "<html><body>shell</body></html>",
            "text": "shell",
            "captured_json": [],
            "error": None,
        }
        mock_rendered.return_value = {
            "success": True,
            "source_method": "rendered",
            "final_url": "https://example.com/jobs/1",
            "status_code": 200,
            "html": "<main><p>Rendered content</p></main>",
            "text": "Rendered content",
            "captured_json": [],
            "error": None,
        }

        result = fetch_best_effort_page("https://example.com/jobs/1")

        self.assertTrue(result["success"])
        self.assertEqual(result["source_method"], "rendered")

    @patch("tracker.services.company_scraper.fetch_rendered_page")
    @patch("tracker.services.company_scraper.fetch_best_effort_page")
    def test_company_scraper_uses_rendered_fallback_when_static_page_is_shell_only(self, mock_best_effort, mock_rendered):
        homepage_url = "https://talent.spa.com"
        mock_best_effort.return_value = {
            "success": True,
            "source_method": "static",
            "final_url": homepage_url,
            "status_code": 200,
            "html": "<html><body><script>app</script></body></html>",
            "text": "",
            "captured_json": [],
            "error": None,
        }
        mock_rendered.return_value = {
            "success": True,
            "source_method": "rendered",
            "final_url": homepage_url,
            "status_code": 200,
            "html": (
                "<html><head><title>SPA</title></head>"
                "<body><main><p>Systems Planning and Analysis provides defense "
                "analytics, mission engineering, and decision support.</p></main>"
                "<a href='/careers'>Careers</a></body></html>"
            ),
            "text": "Systems Planning and Analysis provides defense analytics",
            "captured_json": [],
            "error": None,
        }

        result = scrape_company_info(homepage_url)

        self.assertEqual(result["name"], "SPA")
        self.assertEqual(result["career_url"], "https://talent.spa.com/careers")
        self.assertIn("defense analytics", result["page_content"].lower())