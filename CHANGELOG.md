# Changelog

All notable changes to this project will be documented here.

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

## [0.1.0] - 2025-09-06### Adde

### New

- Gmail OAuth authentication via `gmail_auth.py`
- Message parsing and classification via `parser.py`
- External pattern file `patterns.json` for classification logic
- Initial project structure and Git setup

### Upcoming

- Build SQLite ingestion logic (`db.py`)
- Populate tracker with parsed messages
- Add CLI reporting for job metrics
