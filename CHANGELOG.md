# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.16] - 2026-01-07

### Added
- **Company Alias Input Field** on label_companies page
  - New alias text field after Career/Jobs URL in both new and existing company forms
  - Allows users to define alternative names or abbreviations (e.g., "AFS" for "Accenture Federal Services")
  - Auto-loads existing aliases from companies.json via reverse lookup
  - Saves aliases to companies.json `aliases` object
  - Supports add, update, and remove operations
  - Comprehensive documentation in `markdown/ALIAS_FEATURE.md`

### Changed
- **CompanyEditForm**: Added `alias` non-model field (max 255 chars, optional)
- **label_companies view**: Enhanced to load, initialize, and save alias mappings
- **companies.json**: Alias storage in `{"aliasName": "canonicalCompanyName"}` format

## [1.0.15] - 2026-01-06

### Added
- **Company Homepage Scraper**: Automated web scraping service for extracting company information
  - New `tracker/services/company_scraper.py` module with BeautifulSoup integration
  - Extracts company name (from og:site_name, title, or H1 tags)
  - Extracts domain from URL
  - Finds career/jobs page URLs with smart filtering
  - Handles acronym company names (e.g., "aig" → "AIG", "ibm" → "IBM")
  - 10-second timeout with comprehensive error handling
  - User-Agent header to avoid bot blocking

- **URL-Based Quick Add Company** (label_companies page)
  - Replaced manual company name entry with homepage URL field
  - Automatic web scraping when user enters URL
  - Three-level duplicate detection:
    1. Database check (by name/domain)
    2. companies.json check (known companies and domain mappings)
    3. Auto-create from companies.json if company exists there
  - Redirects to existing company page if duplicate found
  - Prefills new company form with scraped data for review
  - Graceful fallback to manual entry if scraping fails

- **URL-Based Quick Add Company** (label_messages page)
  - Replaced 4-field company registry form with single URL field
  - Identical scraping and duplicate detection as label_companies page
  - Automatic redirect to label_companies for company management
  - Consistent UX across both pages

- **Enhanced Career URL Detection**
  - Priority-based link matching (href keywords → link text keywords)
  - Exclusion patterns for insurance/legal/product pages
  - Filters out social media and unrelated links
  - Removed "employment" keyword to avoid false matches

- **Career URL Persistence**
  - Career/Jobs URL now consistently saved to companies.json `JobSites`
  - Fixed bug where career_url wasn't saved during company creation
  - Properly extracts from form's cleaned_data
  - Updates or creates JobSites entry with scraped URL

### Changed
- **Quick Add Company Flow** (both pages)
  - Single URL input replaces multiple manual fields
  - Automated data extraction reduces manual entry
  - "🔍 Add Company" button with search icon
  - Helper text: "Enter company homepage URL to automatically populate details"

- **Duplicate Prevention Logic**
  - Case-insensitive matching for company names
  - Domain-based detection even if name doesn't match
  - Uses canonical names from companies.json
  - Preserves existing company data (never overwrites)

- **Company Name Cleaning**
  - Removes taglines with em dash separator (e.g., "Microsoft – AI, Cloud..." → "Microsoft")
  - Strips common suffixes (Home, Homepage, Official Site)
  - Handles both single-word and multi-word company names

### Fixed
- Career/Jobs URL field not saving to companies.json during company creation
- AIG homepage scraper now correctly returns "AIG" instead of "aig"
- Microsoft careers page detection (no longer finds Game Pass links)
- Invalid career URLs with employment-practices-liability paths

### Technical Details
- Dependencies: Uses existing `requests` and `beautifulsoup4` packages
- New service module: `tracker/services/company_scraper.py` (200 lines)
- Updated views: `tracker/views/companies.py` and `tracker/views/messages.py`
- Updated templates: `tracker/templates/tracker/label_companies.html` and `label_messages.html`
- Custom exception: `CompanyScraperError` for scraping failures

## [1.0.14] - 2025-12-31

### Fixed
- Fixed company extraction for Boeing emails from ATS domains (myworkday.com)
- Fixed company extraction for Peraton emails from ATS domains (icims.com with +autoreply suffix)
- Fixed `looks_like_person()` false positives for single-word company names like "Boeing"
- Enhanced ATS company extraction to check display name against known companies
- Enhanced ATS company extraction to handle `+` suffixes in email prefixes

### Changed
- Redesigned Ingest New Messages page (reingest_admin) with improved Tailwind CSS styling
- Added single message upload/paste feature to Ingest page (EML/JSON support)
- Improved file upload button visibility with styled blue button
- Added Boeing to companies.json (known, domain_to_company, aliases)

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
