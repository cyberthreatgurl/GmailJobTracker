import json
from pathlib import Path
import shutil

from tracker.services.message_service import MessageService


def test_quick_add_company_updates_json():
    """MessageService.update_company_registry should append expected companies.json entries."""
    # Work on a temporary copy of companies.json to avoid polluting repo during tests
    original_path = Path("json/companies.json")
    temp_path = Path("json/companies.test.json")
    shutil.copy(original_path, temp_path)

    # Monkeypatch the path inside the view by temporarily renaming
    original_backup = original_path.with_suffix(".bak")
    original_path.rename(original_backup)
    temp_path.rename(original_path)
    try:
        added, updated, error = MessageService.update_company_registry(
            company_name="TestCorp",
            company_domain="testcorp.com",
            ats_domain="lever.co",
            careers_url="https://careers.testcorp.com/jobs",
        )

        assert error is None
        assert added
        assert not updated

        data = json.loads(original_path.read_text(encoding="utf-8"))
        assert "TestCorp" in data["known"], "Company name should be added to known list"
        assert data["domain_to_company"].get("testcorp.com") == "TestCorp"
        assert "lever.co" in data["ats_domains"], "ATS domain should be present"
        assert data["JobSites"].get("TestCorp") == "https://careers.testcorp.com/jobs"
    finally:
        # Restore original file
        original_path.rename(temp_path)
        original_backup.rename(original_path)
        temp_path.unlink(missing_ok=True)
