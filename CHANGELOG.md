# Changelog

All notable changes to this project will be documented here.

## [2.1.0] - 2025-09-08

### Added

- Fallback parsing for HTML-only email bodies using BeautifulSoup
- Centralized SQLite connection logic with retry-safe `get_db_connection()` function
- New `email_text` table for ML training (subject + body)
- `insert_email_text()` and `load_training_data()` functions in `db.py`

### Changed

- Parser now prefers `text/plain` but gracefully falls back to `text/html` when needed
- All DB access now routed through `get_db_connection()` for lock safety

### Fixed

- Ignored messages no longer written to `email_text`, preserving ML training quality
- Improved error handling during DB initialization in `main.py`

### Notes

- This version sets the stage for ML-based company prediction using subject + body text
- Recommended tag: `v2.1.0` before vectorization and model training

## [2.0.0] - 2025-09-07

### Added

- Regex-based company extraction for diverse subject formats
- Tokenized ignore logic with normalization
- Dynamic Gmail query builder from patterns.json

### Improved

- Subject parsing coverage for ATS and recruiter formats
- Classification logic excluding ignore phrases

### Notes

- This version serves as baseline before ML integration

## [1.1.0] - 2025-09-07

### Added

- SQLite ingestion logic via db.py, including applications and follow_ups tables
- last_updated timestamp field for audit clarity and sync tracking
- Indexing on status and company fields for performance optimization
- meta table for schema versioning and future migration support
- Parser versioning (PARSER_VERSION) and timezone-aware timestamps in parser.py
- Modular Gmail message ingestion via main.py, with classification and DB integration

### Fixed

- Deprecated datetime.utcnow() replaced with datetime.now(timezone.utc) for proper UTC handling
- Ensured last_updated field is passed through ingestion pipeline and written to DB

### Next

- Parse company, job_title, and job_id from message headers and subject lines
- Modularize date extraction for response_date, rejection_date, interview_date, and follow_up_dates
- Scaffold CLI reporting and export tools for job metrics and application statu

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
