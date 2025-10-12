# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)  
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
---

### 🔹 3. **Update `CHANGELOG.md`**

Add an entry like:

```markdown
## [Unreleased]
### Added
- `check_env.py` script to verify environment readiness (DB, models, patterns, permissions, Git, OAuth, detect-secrets)
- Admin page `/admin/environment_status/` to display environment diagnostics
- Integrated `detect-secrets` scan into `check_env.py`, with auto-generation of `.secrets.baseline` if missing
- Training summary output now displayed on the label admin page after labeling
- ML label and confidence now shown in debug output during message ingestion

### Changed
- `label_messages` view updated to trigger `train_model.py` after labeling
- `label_messages.html` updated to include collapsible training summary block
- `check_env.py` extended to include Git status, Django migrations, directory permissions, and OAuth credential checks

### Added
- `ingest_gmail` command with subject parsing and ignore logic
- `IngestionStats` model for daily ingestion tracking
- `IgnoredMessage` model for ML retraining
- Debug flag to control verbosity

### Changed
- `parse_subject()` now returns structured output with ignore flag
- `ingest_message()` refactored for clean filtering and enrichment
 
---
## 2025-09-11 [dashboard-init-20250911]
- Initial Django dashboard structure pushed
- VS Code settings tailored for ML/Django workflows
- Repo synced from WSL Ubuntu with SSH key authentication

## 2025-09-09 Ingestion Pipeline – Company Extraction & Index Cleanup
- Added Tier 3 domain mapping enrichment: If company is blank after whitelist/heuristics, now populated from patterns.json → domain_to_company.
- Refined Tier 1–4 company cleanup:
- Tier 1: Keep if in known_companies.txt whitelist.
- Tier 2: Keep if passes is_valid_company() heuristics.
- Tier 3: Fallback to domain mapping.
- Tier 4: ML prediction if still blank or generic.
- Removed redundant build_company_job_index() call to avoid unnecessary recomputation.
- Centralized is_valid_company() in db.py for shared use by parser and training logic.
- Impact: New ingestions will have cleaner company values and fewer junk company_job_index entries. Historical rows unchanged; optional backfill can align them.


## [Unreleased]
### Added
- **Story 1:** Added composite index `(company, job_title, job_id)` to DB schema for correlation and dashboard grouping.
- **Story 3:** Implemented domain/email fallback for company name extraction when auto‑extraction fails.
- **Story 6:** Enhanced status classification with keyword + ML hybrid approach.
- `db_helpers.py` with `get_application_by_sender()` for sender/domain correlation checks.
- Correlation logic in `ingest_message()` to keep follow‑ups from known senders within 1 year.
- SQL indexes on `(sender, first_sent DESC)` and `(sender_domain, first_sent DESC)` for fast correlation lookups.

### Changed
- Updated `should_ignore()` to run after correlation check, reducing false positives.
- Cleaned `ignore` patterns in `patterns.json` to remove overly broad terms.
- Ensured `status` and `status_dates` are always assigned before ignore logic to prevent `UnboundLocalError`.

### Fixed
- Corrected DB filename mismatch (`applications.db` → `job_tracker.db`) in `db_helpers.py`.
- Resolved ingestion crash when correlation logic ran before DB schema initialization.

### Security
- Sanitized domain inputs before company name fallback lookup.
- All DB queries use parameterized statements to prevent SQL injection.

### Notes
- These changes lay the groundwork for the MVP dashboard (Stories 1, 3, 6 in `BACKLOG.md`).
- Next step: baseline HTML dashboard with grouping, filters, and responsive design.

---

## [2025-09-08]
### Added
- Colon‑prefix detection to `parse_subject()` for cases like `"MITRE: ..."`
- Known companies preload from `known_companies.txt`
- Sender‑domain mapping from `domain_to_company.json`
- Manual labeling script (`label_companies.py`) for training data

### Changed
- `ingest_message()` now runs ML fallback when company is empty or `"Intel"`
- ML predictions stored in `predicted_company` for review

### Notes
- `known_companies.txt` and `domain_to_company.json` can be expanded anytime
- Next step: integrate `sender_domain` capture in `extract_metadata()`

---

## [2.1.0] - 2025-09-08
### Added
- Fallback parsing for HTML‑only email bodies using BeautifulSoup
- Centralized SQLite connection logic with retry‑safe `get_db_connection()` function
- New `email_text` table for ML training (subject + body)
- `insert_email_text()` and `load_training_data()` functions in `db.py`

### Changed
- Parser now prefers `text/plain` but gracefully falls back to `text/html` when needed
- All DB access now routed through `get_db_connection()` for lock safety

### Fixed
- Ignored messages no longer written to `email_text`, preserving ML training quality
- Improved error handling during DB initialization in `main.py`

### Notes
- This version sets the stage for ML‑based company prediction using subject + body text
- Recommended tag: `v2.1.0` before vectorization and model training

---

## [2.0.0] - 2025-09-07
### Added
- Regex‑based company extraction for diverse subject formats
- Tokenized ignore logic with normalization
- Dynamic Gmail query builder from `patterns.json`

### Improved
- Subject parsing coverage for ATS and recruiter formats
- Classification logic excluding ignore phrases

### Notes
- This version serves as baseline before ML integration

---

## [1.1.0] - 2025-09-07
### Added
- SQLite ingestion logic via `db.py`, including `applications` and `follow_ups` tables
- `last_updated` timestamp field for audit clarity and sync tracking
- Indexing on `status` and `company` fields for performance optimization
- `meta` table for schema versioning and future migration support
- Parser versioning (`PARSER_VERSION`) and timezone‑aware timestamps in `parser.py`
- Modular Gmail message ingestion via `main.py`, with classification and DB integration

### Fixed
- Deprecated `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` for proper UTC handling
- Ensured `last_updated` field is passed through ingestion pipeline and written to DB

### Next
- Parse company, job_title, and job_id from message headers and subject lines
- Modularize date extraction for `response_date`, `rejection_date`, `interview_date`, and `follow_up_dates`
- Scaffold CLI reporting and export tools for job metrics and application status

---

## [0.1.0] - 2025-09-06
### New
- Gmail OAuth authentication via `gmail_auth.py`
- Message parsing and classification via `parser.py`
- External pattern file `patterns.json` for classification logic
- Initial project structure and Git setup

### Upcoming
- Build SQLite ingestion logic (`db.py`)
- Populate tracker with parsed messages
- Add CLI reporting for job metrics