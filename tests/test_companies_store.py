"""Unit tests for tracker.utils.companies_io.CompaniesStore.

All tests use a temp file so the real companies.json is never touched.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tracker.utils.companies_io import CompaniesStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(initial: dict) -> tuple[CompaniesStore, Path]:
    """Write *initial* to a temp file and return (store, path)."""
    fd, path_str = tempfile.mkstemp(suffix=".json")
    path = Path(path_str)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(initial, f, indent=2)
    return CompaniesStore(path), path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# classify_domain
# ---------------------------------------------------------------------------

class TestClassifyDomain:

    def test_domain_moved_to_ats(self):
        initial = {"domain_to_company": {"acme.com": "Acme"}, "ats_domains": []}
        store, p = _make_store(initial)
        changed = store.classify_domain("acme.com", "ats", source="test")
        assert changed is True
        data = _load(p)
        assert "acme.com" not in data["domain_to_company"]
        assert "acme.com" in data["ats_domains"]

    def test_domain_moved_to_headhunter(self):
        initial = {"ats_domains": ["rec.com"], "headhunter_domains": []}
        store, p = _make_store(initial)
        changed = store.classify_domain("rec.com", "headhunter", source="test")
        assert changed is True
        data = _load(p)
        assert "rec.com" not in data["ats_domains"]
        assert "rec.com" in data["headhunter_domains"]

    def test_domain_classified_as_company_with_name(self):
        initial = {}
        store, p = _make_store(initial)
        changed = store.classify_domain("beta.io", "company", company_name="BetaCo", source="test")
        assert changed is True
        data = _load(p)
        assert data["domain_to_company"]["beta.io"] == "BetaCo"

    def test_domain_classified_as_company_fallback_name(self):
        initial = {}
        store, p = _make_store(initial)
        store.classify_domain("mycompany.com", "company", source="test")
        data = _load(p)
        # fallback uses second-to-last label: "mycompany"
        assert data["domain_to_company"]["mycompany.com"] == "Mycompany"

    def test_personal_removes_from_company_side(self):
        initial = {
            "domain_to_company": {"me.com": "MeCorp"},
            "ats_domains": [],
            "headhunter_domains": [],
            "job_boards": [],
        }
        store, p = _make_store(initial)
        changed = store.classify_domain("me.com", "personal", source="test")
        assert changed is True
        data = _load(p)
        assert "me.com" not in data["domain_to_company"]

    def test_idempotent_no_write_when_unchanged(self):
        initial = {"ats_domains": ["lever.co"]}
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime
        changed = store.classify_domain("lever.co", "ats", source="test")
        assert changed is False
        assert p.stat().st_mtime == mtime_before

    def test_job_board_variant(self):
        initial = {"job_boards": []}
        store, p = _make_store(initial)
        store.classify_domain("indeed.com", "job_boards", source="test")
        data = _load(p)
        assert "indeed.com" in data["job_boards"]

    def test_company_name_update(self):
        """Reclassifying an existing company domain updates the name."""
        initial = {"domain_to_company": {"old.com": "OldName"}}
        store, p = _make_store(initial)
        changed = store.classify_domain("old.com", "company", company_name="NewName", source="test")
        assert changed is True
        data = _load(p)
        assert data["domain_to_company"]["old.com"] == "NewName"


# ---------------------------------------------------------------------------
# classify_domains (batch)
# ---------------------------------------------------------------------------

class TestClassifyDomains:

    def test_batch_all_same_type(self):
        initial = {"ats_domains": []}
        store, p = _make_store(initial)
        count = store.classify_domains(
            ["a.io", "b.io", "c.io"], "ats", source="test"
        )
        assert count == 3
        data = _load(p)
        assert set(data["ats_domains"]) == {"a.io", "b.io", "c.io"}

    def test_batch_with_company_names_map(self):
        initial = {}
        store, p = _make_store(initial)
        count = store.classify_domains(
            ["x.com", "y.com"],
            "company",
            company_names_map={"x.com": "XCorp", "y.com": "YCorp"},
            source="test",
        )
        assert count == 2
        data = _load(p)
        assert data["domain_to_company"]["x.com"] == "XCorp"
        assert data["domain_to_company"]["y.com"] == "YCorp"

    def test_batch_empty_list_no_write(self):
        initial = {}
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime
        count = store.classify_domains([], "ats", source="test")
        assert count == 0
        assert p.stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# apply_domain_classifications (heterogeneous batch)
# ---------------------------------------------------------------------------

class TestApplyDomainClassifications:

    def test_mixed_types_single_write(self):
        initial = {}
        store, p = _make_store(initial)
        labels = [
            {"domain": "co.com", "label_type": "company", "company_name": "BigCo"},
            {"domain": "hr.io", "label_type": "headhunter"},
            {"domain": "jobs.net", "label_type": "ats"},
        ]
        count = store.apply_domain_classifications(labels, source="test")
        assert count == 3
        data = _load(p)
        assert data["domain_to_company"]["co.com"] == "BigCo"
        assert "hr.io" in data["headhunter_domains"]
        assert "jobs.net" in data["ats_domains"]

    def test_removal_via_personal(self):
        initial = {
            "domain_to_company": {"gone.com": "Gone"},
            "ats_domains": [],
            "headhunter_domains": [],
            "job_boards": [],
        }
        store, p = _make_store(initial)
        store.apply_domain_classifications(
            [{"domain": "gone.com", "label_type": "personal"}], source="test"
        )
        data = _load(p)
        assert "gone.com" not in data["domain_to_company"]


# ---------------------------------------------------------------------------
# merge_domain_mappings
# ---------------------------------------------------------------------------

class TestMergeDomainMappings:

    def test_adds_new_entries_only(self):
        initial = {
            "domain_to_company": {"existing.com": "Existing"},
            "ats_domains": ["workday.com"],
            "headhunter_domains": [],
        }
        store, p = _make_store(initial)
        count = store.merge_domain_mappings(
            dtc_additions={"existing.com": "ShouldNotOverwrite", "new.com": "New"},
            ats_additions={"workday.com", "lever.co"},
            headhunter_additions={"recruiter.io"},
            source="test",
        )
        assert count == 3  # new.com, lever.co, recruiter.io
        data = _load(p)
        assert data["domain_to_company"]["existing.com"] == "Existing"  # unchanged
        assert data["domain_to_company"]["new.com"] == "New"
        assert "lever.co" in data["ats_domains"]
        assert "recruiter.io" in data["headhunter_domains"]

    def test_no_additions_no_write(self):
        initial = {"domain_to_company": {"here.com": "Here"}}
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime
        count = store.merge_domain_mappings({"here.com": "Any"}, source="test")
        assert count == 0
        assert p.stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# register_company
# ---------------------------------------------------------------------------

class TestRegisterCompany:

    def test_adds_all_fields(self):
        initial = {}
        store, p = _make_store(initial)
        changed = store.register_company(
            "Acme",
            domain="acme.com",
            ats_domain="lever.co",
            career_url="https://acme.com/jobs",
            aliases=["Acme Corp", "ACME"],
            source="test",
        )
        assert changed is True
        data = _load(p)
        assert "Acme" in data["known"]
        assert data["domain_to_company"]["acme.com"] == "Acme"
        assert "lever.co" in data["ats_domains"]
        assert data["JobSites"]["Acme"] == "https://acme.com/jobs"
        assert data["aliases"]["Acme Corp"] == "Acme"
        assert data["aliases"]["ACME"] == "Acme"

    def test_no_overwrite_by_default(self):
        initial = {
            "known": ["Acme"],
            "domain_to_company": {"acme.com": "Acme"},
        }
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime
        changed = store.register_company("Acme", domain="acme.com", source="test")
        assert changed is False
        assert p.stat().st_mtime == mtime_before

    def test_overwrite_domain_when_flag_set(self):
        initial = {"domain_to_company": {"acme.com": "OldName"}, "known": []}
        store, p = _make_store(initial)
        changed = store.register_company(
            "NewName", domain="acme.com", overwrite_domain=True, source="test"
        )
        assert changed is True
        data = _load(p)
        assert data["domain_to_company"]["acme.com"] == "NewName"

    def test_overwrite_career_url_when_flag_set(self):
        initial = {"known": ["Co"], "JobSites": {"Co": "https://old.com"}}
        store, p = _make_store(initial)
        changed = store.register_company(
            "Co",
            career_url="https://new.com",
            overwrite_career_url=True,
            source="test",
        )
        assert changed is True
        data = _load(p)
        assert data["JobSites"]["Co"] == "https://new.com"


# ---------------------------------------------------------------------------
# sync_registry_snapshot
# ---------------------------------------------------------------------------

class TestSyncRegistrySnapshot:

    def test_updates_db_backed_sections_only(self):
        initial = {
            "known": ["OldCo"],
            "ats_domains": ["old-ats.com"],
            "domain_to_company": {"oldco.com": "OldCo"},
            "aliases": {"Old": "OldCo"},
            "JobSites": {"KeepCo": "https://keep.example/jobs"},
            "job_boards": ["indeed.com"],
            "headhunter_domains": ["recruiter.example"],
        }
        store, p = _make_store(initial)

        changed = store.sync_registry_snapshot(
            known=["NewCo"],
            ats_domains=["new-ats.com"],
            domain_to_company={"newco.com": "NewCo"},
            aliases={"New": "NewCo"},
            source="test",
        )

        assert changed is True
        data = _load(p)
        assert data["known"] == ["NewCo"]
        assert data["ats_domains"] == ["new-ats.com"]
        assert data["domain_to_company"] == {"newco.com": "NewCo"}
        assert data["aliases"] == {"New": "NewCo"}
        assert data["JobSites"] == {"KeepCo": "https://keep.example/jobs"}
        assert data["job_boards"] == ["indeed.com"]
        assert data["headhunter_domains"] == ["recruiter.example"]

    def test_no_write_when_snapshot_is_unchanged(self):
        initial = {
            "known": ["Acme"],
            "ats_domains": ["workday.com"],
            "domain_to_company": {"acme.com": "Acme"},
            "aliases": {"ACME": "Acme"},
            "JobSites": {"Acme": "https://acme.example/jobs"},
        }
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime

        changed = store.sync_registry_snapshot(
            known=["Acme"],
            ats_domains=["workday.com"],
            domain_to_company={"acme.com": "Acme"},
            aliases={"ACME": "Acme"},
            source="test",
        )

        assert changed is False
        assert p.stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# update_company
# ---------------------------------------------------------------------------

class TestUpdateCompany:

    def test_domain_rename(self):
        initial = {"domain_to_company": {"old.com": "Acme"}}
        store, p = _make_store(initial)
        changed = store.update_company("Acme", new_domain="new.com", source="test")
        assert changed is True
        data = _load(p)
        assert "old.com" not in data["domain_to_company"]
        assert data["domain_to_company"]["new.com"] == "Acme"

    def test_domain_clear(self):
        initial = {"domain_to_company": {"acme.com": "Acme"}}
        store, p = _make_store(initial)
        changed = store.update_company("Acme", new_domain="", source="test")
        assert changed is True
        assert "acme.com" not in _load(p)["domain_to_company"]

    def test_career_url_set(self):
        initial = {"known": ["Acme"]}
        store, p = _make_store(initial)
        store.update_company("Acme", career_url="https://acme.com/careers", source="test")
        assert _load(p)["JobSites"]["Acme"] == "https://acme.com/careers"

    def test_career_url_clear(self):
        initial = {"known": ["Acme"], "JobSites": {"Acme": "https://acme.com/careers"}}
        store, p = _make_store(initial)
        store.update_company("Acme", career_url="", source="test")
        assert "Acme" not in _load(p).get("JobSites", {})

    def test_ats_domain_added(self):
        initial = {"known": ["Acme"], "ats_domains": []}
        store, p = _make_store(initial)
        store.update_company("Acme", ats_domain="workday.com", source="test")
        assert "workday.com" in _load(p)["ats_domains"]

    def test_ats_domain_not_duplicated(self):
        initial = {"known": ["Acme"], "ats_domains": ["workday.com"]}
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime
        changed = store.update_company("Acme", ats_domain="workday.com", source="test")
        assert changed is False
        assert p.stat().st_mtime == mtime_before

    def test_aliases_replace(self):
        initial = {
            "aliases": {"OldAlias": "Acme", "AlsoOld": "Acme"},
        }
        store, p = _make_store(initial)
        store.update_company("Acme", new_aliases=["NewAlias"], source="test")
        data = _load(p)
        assert "OldAlias" not in data["aliases"]
        assert "AlsoOld" not in data["aliases"]
        assert data["aliases"]["NewAlias"] == "Acme"

    def test_aliases_clear(self):
        initial = {"aliases": {"OldAlias": "Acme"}}
        store, p = _make_store(initial)
        store.update_company("Acme", new_aliases=[], source="test")
        assert "OldAlias" not in _load(p).get("aliases", {})

    def test_unchanged_sentinel_leaves_domain_alone(self):
        initial = {"domain_to_company": {"acme.com": "Acme"}}
        store, p = _make_store(initial)
        mtime_before = p.stat().st_mtime
        # new_domain defaults to _UNCHANGED — should not touch domain_to_company
        changed = store.update_company("Acme", career_url="", source="test")
        # career_url="" on empty JobSites → no-op
        assert changed is False
        assert p.stat().st_mtime == mtime_before
        assert _load(p)["domain_to_company"]["acme.com"] == "Acme"

    def test_atomic_write_no_temp_file_left(self):
        """The .tmp file produced during write must not persist after success."""
        initial = {}
        store, p = _make_store(initial)
        store.update_company("Acme", new_domain="acme.com", source="test")
        leftover = list(p.parent.glob("*.tmp"))
        assert not leftover, f"Leftover temp files: {leftover}"


# ---------------------------------------------------------------------------
# Non-existent file creates it
# ---------------------------------------------------------------------------

def test_register_creates_file_if_missing(tmp_path):
    path = tmp_path / "companies_new.json"
    assert not path.exists()
    store = CompaniesStore(path)
    store.register_company("StartupCo", domain="startup.io", source="test")
    assert path.exists()
    data = _load(path)
    assert "StartupCo" in data["known"]
    assert data["domain_to_company"]["startup.io"] == "StartupCo"


# ---------------------------------------------------------------------------
# safe_write_companies_json (shrinkage guard)
# ---------------------------------------------------------------------------

def test_safe_write_blocks_shrinkage(tmp_path):
    from tracker.utils.companies_io import safe_write_companies_json

    large = {
        "domain_to_company": {f"d{i}.com": f"Co{i}" for i in range(100)},
        "known": [f"Co{i}" for i in range(100)],
        "aliases": {},
    }
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(large), encoding="utf-8")

    tiny = {"domain_to_company": {}, "known": [], "aliases": {}}
    result = safe_write_companies_json(path, tiny, source="test")
    assert result is False
    # File should be unchanged
    assert json.loads(path.read_text())["known"] == large["known"]


def test_safe_write_allows_full_replace(tmp_path):
    from tracker.utils.companies_io import safe_write_companies_json

    original = {
        "domain_to_company": {"a.com": "A"},
        "known": ["A"],
        "aliases": {},
    }
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(original), encoding="utf-8")

    updated = {
        "domain_to_company": {"a.com": "A", "b.com": "B"},
        "known": ["A", "B"],
        "aliases": {},
    }
    result = safe_write_companies_json(path, updated, source="test")
    assert result is True
    assert "B" in json.loads(path.read_text())["known"]
