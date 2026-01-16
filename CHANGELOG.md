# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.3] - 2026-01-16

### Fixed
- **Newsletter Override for ATS Emails** - Added pattern `\byour\s+\w+\s+application\s+for\b` to application patterns
  - Matches subject lines like "Your Guidehouse Application for 34202 Cyber Security Engineer"
  - Ensures ATS emails with List-Unsubscribe headers are not incorrectly ignored as newsletters
  - Fixes Workday/Greenhouse emails that use unsubscribe headers being misclassified

## [1.2.2] - 2026-01-16

### Added
- **⚠️ Missing Applications Report** - New dashboard page to find companies with rejections but missing application confirmations
  - Accessible at `/missing_applications/` or via Quick Actions dropdown
  - Shows companies where rejection count exceeds application count
  - Displays application, rejection, and interview counts per company
  - Lists recent rejection subjects for context
  - Quick action buttons: "➕ Add" links to manual entry with company pre-filled, "📧 View" links to company messages
  - Summary stats: total affected companies and total missing applications
  - Help section explaining common reasons for missing applications

### Fixed
- **Rejection Pattern Fix** - Moved "thank you for your interest" from application to rejection patterns
  - Subject line "Thank you for your interest" is commonly used in rejection emails (e.g., Capital One)
  - Added patterns for "unable to consider you" and "moving forward with other applicants"
  - Fixes misclassification of rejection emails as job_application

## [1.2.1] - 2026-01-16

### Added
- **📋 Manual Entry CRUD Operations** - Complete edit/delete functionality for manual entries
  - Edit button on each manual entry to update details
  - Delete button with confirmation for individual entries
  - Bulk delete with "Select All" checkbox and count indicator
  - New URL routes: `/manual_entry/<thread_id>/edit/` and `/manual_entry/<thread_id>/delete/`
  - Company dropdown selector with "- New Company -" option for creating new companies during entry

- **🎯 Focus Area Word Cloud Filter** - Dashboard word cloud now links to Job Search Tracker
  - Clicking a word filters to companies with that focus area
  - New `focus_area` URL parameter: `/job_search_tracker/?focus_area=Cybersecurity`
  - Clear Filter button to remove focus area filter
  - Filter badge shows active focus area

- **📊 Dashboard Chart Improvements**
  - Series dropdown menu replaces inline checkboxes (cleaner UI)
  - "Today" added as default date range option
  - Two-row layout for chart controls (Row 1: date range, Row 2: X-Axis/Series)
  - Word cloud links navigate to filtered Job Search Tracker

- **🔍 Enhanced Company Scraping** - Multi-page crawling for better focus area analysis
  - Now crawls About, Solutions, Technology, and Industries pages
  - Combines content from multiple internal pages for analysis
  - Shows which pages were analyzed in focus area results
  - Improved AI-suggested focus areas with bullet-point formatting

- **🏢 Company Admin Merge Action** - Admin can now select multiple companies to merge
  - "🔗 Merge selected companies" action in Django admin
  - Redirects to merge interface with pre-selected companies

- **📝 Notes Section for Companies** - Expandable Notes section in label_companies
  - Company focus area analysis appears in Notes field after Populate
  - Persist errors and analysis results for reference
  - Larger textarea with proper styling

- **📅 Application Date Field** - Added sent_date (Application Date) to Application Details
  - Editable date field in Application Details section
  - Auto-populated from ThreadTracking.sent_date
  - Syncs when switching between multiple applications

- **✏️ Edit Icon in Job Search Tracker** - Quick link to edit company profile
  - Pencil icon next to company name in Job Search Tracker table
  - Links directly to `/label_companies/?company=ID`

### Changed
- **🔄 Auto-Calculate Company Status** - Status now auto-updates based on latest message
  - Removed manual "Mark as Ghosted" button (now automatic)
  - Status reflects: rejected, interview, application, ghosted (based on GHOSTED_DAYS_THRESHOLD)
  - Companies with status="new" are protected from auto-update
  - New management command: `update_company_statuses` 

- **📧 .eml Import ThreadTracking** - EML uploads now create proper ThreadTracking records
  - Automatically creates ThreadTracking for job_application and interview_invite labels
  - Propagates label changes to existing ThreadTracking records
  - Application Details section now shows correctly after EML upload

- **🎯 Dashboard Company Filter Removed** - Simplified dashboard layout
  - Company dropdown changed to "Go to Company" navigation
  - Selecting a company navigates to label_companies page
  - Chart data no longer filtered by single company

- **⏰ Dashboard Timezone Fix** - All JavaScript date handling uses local timezone
  - Fixed UTC vs local time discrepancy in chart display
  - Date inputs, week/month grouping, and quick range all use local time
  - Dates now display correctly in America/New_York timezone

- **❌ Populate Error Handling** - Errors now appear in Notes field
  - Failed scrape attempts log error to company Notes
  - AJAX response includes `notes` field for error context
  - Status messages show above form fields

### Fixed
- **🏢 Dragos Company Mapping** - Fixed companies.json domain mapping
  - Changed `"dragos.com": "Your Partner in OT Cybersecurity"` → `"dragos.com": "Dragos"`
  - Application Details now correctly associate with Dragos company
  - ThreadTracking records properly linked

- **📊 Application Details Empty** - Fixed Application Details section not showing
  - Added sync_message_threadtracking_labels management command
  - Fixes ThreadTracking.ml_label mismatches with Message.ml_label
  - fix_missing_threadtracking script creates missing records

- **🔢 Manual Entry ml_label Mapping** - Fixed manual entry labels
  - "application" → "job_application" (matches system labels)
  - "interview" → "interview_invite" (matches system labels)
  - Manual entries now appear correctly in dashboard stats

### Technical Details
- Modified tracker/forms.py: Company dropdown with new company creation option
- Modified tracker/forms_company.py: Added sent_date to ApplicationDetailsForm, improved notes widget
- Modified tracker/views/applications.py: Added edit_manual_entry, delete_manual_entry, bulk_delete_manual_entries
- Modified tracker/views/companies.py: AJAX populate/save, auto-status calculation, scraper helper function
- Modified tracker/views/dashboard.py: Removed company filter, simplified chart data queries
- Modified tracker/templates/tracker/dashboard.html: Two-row chart controls, Series dropdown, local timezone JS
- Modified tracker/templates/tracker/label_companies.html: Notes section, AJAX functions, application date field
- Modified tracker/templates/tracker/manual_entry.html: Edit/delete buttons, bulk delete, company dropdown
- Modified tracker/templates/tracker/job_search_tracker.html: Focus area filter, edit icon
- Modified tracker/admin.py: Merge action for companies
- Modified tracker/urls.py: New manual entry edit/delete routes
- Modified parser.py: EML import creates ThreadTracking records
- Modified tracker/services/company_scraper.py: Multi-page crawling, improved focus analysis
- Added tracker/management/commands/sync_message_threadtracking_labels.py
- Added tracker/management/commands/update_company_statuses.py
- Added scripts/check_label_mismatches.py, fix_missing_threadtracking.py, debug_mismatches.py

## [1.2.0] - 2026-01-15

### Added
- **💼 Job Title Field** - Added editable Job Title field to Application Details section
  - Displays existing job title from ThreadTracking records
  - Allows manual editing and saving via "Save Application Details" button
  - Added job_title to ApplicationDetailsForm fields list
  - Auto-populated from message subjects during sync_threadtracking

- **🔄 Manual Job Posting Scraper** - Added explicit "Scrape Text" button for job posting URLs
  - Replaced auto-scraping with user-initiated button click
  - Green "🔄 Scrape Text" button next to Application URL field
  - Shows loading state ("⏳ Scraping...") during fetch
  - Displays character count in success notification
  - Better User-Agent headers for macOS Chrome
  - BambooHR-specific content selectors
  - Fallback to largest text container when selectors don't match
  - Debug HTML saving to /tmp/scrape_debug.html for troubleshooting
  - Enhanced error messages for JavaScript-rendered content

- **📅 Upcoming Interviews/Prescreens Display** - Improved sidebar "Upcoming" section
  - Now shows both prescreen_date and interview_date fields
  - Clear differentiation: 📞 Prescreen vs 💼 Interview icons
  - Multi-line format with company name as clickable link
  - Displays both dates when applicable (sorted chronologically)
  - Clickable company names navigate to label_companies page
  - Fixed query to check prescreen_date >= today (not ml_label='prescreen')
  - Date comparison uses .date() instead of datetime for accuracy

### Fixed
- **📝 Notes Field Not Saving** - Fixed company notes not persisting on label_companies page
  - Added "notes" to CompanyEditForm Meta.fields list
  - Notes now save when clicking "Save Changes" button
  - Properly included in form validation and processing

- **🔧 .eml Upload ThreadTracking Fix** - Fixed Application Details not showing for manually uploaded emails
  - .eml ingestion now updates ThreadTracking.ml_label after classification
  - Previously created Message with ml_label but left ThreadTracking with null
  - Template filter for ml_label='job_application' now works correctly
  - Added fix_eml_threadtracking management command for existing records
  - sync_threadtracking properly creates records for job_application messages

- **🗓️ Upcoming Events Query** - Fixed upcoming interviews/prescreens not displaying
  - Changed from checking ml_label='prescreen' to prescreen_date >= today
  - Now checks both interview_date and prescreen_date fields
  - Fixed date comparison to use .date() for proper DateField matching
  - Properly orders by interview_date and prescreen_date

- **🌐 Job Posting Scraper Errors** - Improved scraping reliability and error handling
  - Fixed URLSearchParams formatting for POST request body
  - Added detailed server-side logging for debugging
  - Suppressed BeautifulSoup encoding warnings
  - Better error messages displayed to user
  - Returns 200 status with error message for client-side handling

### Technical Details
- Modified tracker/forms_company.py: Added job_title and notes to form fields
- Modified tracker/templates/tracker/label_companies.html: 
  - Added Job Title input field to Application Details section
  - Changed Application URL to inline button layout
  - Updated JavaScript to manual scrape with better error handling
- Modified tracker/templates/tracker/_sidebar.html: Enhanced upcoming events display with icons and links
- Modified tracker/services/stats_service.py: Fixed upcoming query to use date fields instead of ml_label
- Modified tracker/views/companies.py: Enhanced scrape_job_posting with logging and better headers
- Modified scripts/ingest_eml.py: Update ThreadTracking.ml_label after classification
- Added tracker/management/commands/fix_eml_threadtracking.py: Fix existing null ml_label records

## [1.1.1] - 2026-01-13

### Fixed
- **🔧 Company Alias Resolution** - Fixed duplicate company creation when aliases exist
  - Added `resolve_company_alias()` function to check CompanyAlias model before creating companies
  - Updated all 6 `Company.objects.get_or_create()` calls in parser.py to resolve aliases first
  - Prevents duplicate companies like "CGI" (Company #201) when alias points to "CGI Inc." (Company #200)
  - Aliases now properly resolve to canonical company names during email ingestion

- **⏰ Jobs Searched Timezone Fix** - Fixed "Jobs Searched" counter to respect local timezone
  - Changed `now().replace()` to `timezone.localtime(now())` in stats_service.py
  - Properly calculates midnight in local timezone instead of UTC
  - "Jobs Searched" counter now correctly counts all companies searched today in America/New_York timezone
  - Added `timezone` import to stats_service.py

- **🌍 Timezone Configuration** - TIME_ZONE setting now reads from environment variable
  - Updated settings.py to use `os.getenv("TZ", "America/New_York")` instead of hardcoded value
  - Respects TZ environment variable from .env file for consistent timezone handling

### Technical Details
- Modified parser.py: Added resolve_company_alias() function and updated 6 company creation points
- Modified tracker/services/stats_service.py: Fixed timezone calculation for daily stats
- Modified dashboard/settings.py: TIME_ZONE now reads from TZ environment variable

## [1.1.0] - 2026-01-11

### Added
- **🔍 Job Search Tracker** - New proactive job search management feature
  - Dedicated page at `/job_search_tracker/` to track manual company website searches
  - Added `last_job_search_date` field to Company model (migration 0015)
  - Track which companies you've manually searched for job opportunities
  - "Searched Today" button per company to mark search timestamp
  - Sortable table columns (Company, Last Search Date, Messages)
  - Statistics dashboard showing:
    - Total companies
    - Ever searched count
    - Never searched count
    - Searched today count
    - Searched this week count
  - Sidebar integration with "Job Searches Today" count
  - New "Added Today" counter in sidebar showing companies added in last 24 hours
  - Checkbox on label_companies page to mark company as manually searched
  - Displays last search date with "time since" formatting

### Changed
- **StatsService**: Added `companies_searched_count` and `companies_added_today` metrics to sidebar
- **label_companies view**: Added POST handler for `mark_searched` checkbox
- **Sidebar template**: Added "Job Searches Today" and "Added Today" stats with links
- **URL routing**: Added `job_search_tracker` route
- **Company model**: Enhanced with job search tracking capability

### UI/UX
- Modern Tailwind CSS styling with gradient backgrounds
- Color-coded stat cards with left border accents
- Responsive design for mobile and desktop
- Hover effects and smooth transitions
- Badge-style pills for dates and message counts
- Two-column help section with usage instructions and sorting tips

## [1.0.16] - 2026-01-07

### Added
- **Comprehensive Input Validation** across all forms and models
  - **HTML5 Browser Validation**: Pattern attributes on text inputs, type="url" for URLs
  - **Django Form Validation**: RegexValidator on all text fields (company name, job title, job ID, alias, source, thread_id)
  - **Django Model Validation**: Field-level validators on Company and ThreadTracking models
  - **URL Validation**: URLValidator with http/https schemes on homepage and career_url
  - **Allowed Characters**:
    - Text fields: Alphanumeric + period (.), comma (,), dash (-)
    - Company names/aliases: Also allows ampersand (&), quotes, parentheses
    - Job titles: Also allows forward slash (/), parentheses, ampersand
    - Domains: Alphanumeric + period, dash
    - Job IDs: Alphanumeric + dash, underscore
    - Thread IDs: Alphanumeric only
  - Comprehensive documentation in `markdown/INPUT_VALIDATION.md`
  - Migration 0014 created for model validator changes

- **Company Alias Input Field** on label_companies page
  - New alias text field after Career/Jobs URL in both new and existing company forms
  - Allows users to define alternative names or abbreviations (e.g., "AFS" for "Accenture Federal Services")
  - Auto-loads existing aliases from companies.json via reverse lookup
  - Saves aliases to companies.json `aliases` object
  - Supports add, update, and remove operations
  - Comprehensive documentation in `markdown/ALIAS_FEATURE.md`

### Changed
- **CompanyEditForm**: Added `alias` non-model field with regex validation (max 255 chars, optional)
- **ManualEntryForm**: Added regex validators to company_name, job_title, job_id, source fields
- **UploadEmlForm**: Added regex validator to thread_id field
- **Company Model**: Added validators to name, domain, ats, homepage, contact_name fields
- **ThreadTracking Model**: Added validators to thread_id, job_title, job_id fields
- **Templates**: Added HTML5 pattern validation to search box, gmail label prefix inputs
- **label_companies view**: Enhanced to load, initialize, and save alias mappings
- **companies.json**: Alias storage in `{"aliasName": "canonicalCompanyName"}` format

### Security
- **XSS Prevention**: Input validation blocks HTML tags, JavaScript protocols, malicious patterns
- **SQL Injection Prevention**: Django ORM parameterized queries + validators prevent malicious input
- **Three-Layer Validation**: HTML5 (client) → Django Forms (server) → Django Models (database)

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
