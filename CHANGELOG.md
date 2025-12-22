# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.10] - 2025-12-22

### Fixed
- Fixed headhunter company assignment bug where "HeadHunter" literal was assigned instead of None during re-ingestion
- Fixed path resolution in runserver command for Gmail auth status display (parents[4] → parents[3])
- Fixed referral email misclassification (Workday employee referrals no longer classified as noise)

### Added
- Gmail API authentication status display in runserver command
  - Shows credentials.json validity with client ID
  - Shows token.pickle expiry status with days remaining
  - Color-coded warnings for expiring/expired tokens
  - Actionable instructions for missing/expired credentials
- Referral detection patterns for Workday employee referrals
  - "just referred you to" pattern
  - "congratulations...referred...to work at" subject line pattern
- Noise pattern exclusions for referral keywords to prevent false classification

### Changed
- Headhunter messages now correctly set company=None during re-ingestion
- ThreadTracking updates now skip headhunter messages (label="head_hunter")
- Improved early referral detection to run before noise classification

## [1.0.0] - 2025-12-19

### Added
- Gmail API integration with OAuth2 authentication
- Hybrid ML + regex message classification (6 message types: job_application, interview_invite, rejection, head_hunter, noise, other)
- 4-tier company resolution system (whitelist → domain mapping → ATS detection → regex fallback)
- Django web dashboard with threaded message view
- Bulk labeling interface with auto-retraining (every 20 labels)
- ML model training and automatic retraining
- SQLite local storage (privacy-first, no cloud sync)
- Docker deployment support with docker-compose
- CI/CD pipeline with GitHub Actions (lint, test, build, security scanning)
- Secret scanning with detect-secrets baseline enforcement
- Configuration-driven classification (patterns.json, companies.json)
- ATS-aware company resolution (Greenhouse, Workday, Lever, etc.)
- Company alias management and domain mapping
- Comprehensive documentation (GETTING_STARTED.md, CONTRIBUTING.md, COMMAND_REFERENCE.md)
- Management commands (ingest_gmail, reclassify_messages, mark_newsletters_ignored)
- Weekly/monthly statistics dashboard
- Confidence scoring for ML predictions
- Newsletter detection and auto-ignore functionality

### Security
- detect-secrets baseline enforcement in CI
- OAuth read-only Gmail scope
- 100% local-only data storage
- No telemetry or external API calls
- Secret scanning enabled for public repository
- Push protection for credential commits

### Documentation
- Complete 15-minute setup guide
- Architecture diagrams (Mermaid flowcharts)
- Command reference documentation
- Public repository setup guide
- GitHub Secrets usage guide
- Extraction logic documentation
- Dashboard overview guide
- Docker deployment guide
- Contributing guidelines

[1.0.10]: https://github.com/cyberthreatgurl/GmailJobTracker/releases/tag/v1.0.10
[1.0.0]: https://github.com/cyberthreatgurl/GmailJobTracker/releases/tag/v1.0.0
