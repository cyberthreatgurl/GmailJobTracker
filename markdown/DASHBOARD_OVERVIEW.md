# DASHBOARD_OVERVIEW.md

## Overview

This dashboard provides a secure, local-only interface for tracking job applications, interviews, and message threads with intelligent classification and company extraction.

---

## Features

### Core Functionality
- **Threaded message viewer** per company
- **Weekly/monthly statistics** for rejections and interviews
- **Upcoming interview calendar**
- **Interactive labeling interface** with auto-retraining
- **Label debugger** with priority-order testing at `/label-companies/`
- **Environment diagnostics** via `/admin/environment_status/`

### Intelligent Classification
- **Hybrid ML + Rule-based**: Rules override ML for noise/offer/head_hunter
- **Header analysis**: Automatic newsletter/bulk mail detection
- **Meeting detection**: Distinguishes interviews from general meetings
- **Person-name filtering**: Prevents person names as company names
- **Priority-ordered labels**: 10-level classification hierarchy

### Company Extraction
- **9-stage extraction pipeline**: Domain mapping → ATS detection → body parsing → Organization header
- **Subdomain support**: Matches both apex and subdomains
- **ATS integration**: Greenhouse, Lever, Workday, etc.
- **Indeed special handling**: Extracts actual employer from body text
- **Organization header fallback**: Uses email headers when other methods fail

---

## Architecture

- **Framework**: Django 5.2.7
- **Database**: SQLite (`job_tracker.db`)
- **Models**: `Message`, `ThreadTracking`, `Company`, `IgnoredMessage`, `IngestionStats`
- **ML Pipeline**: 
  - Subject classifier: `model/subject_classifier.pkl`
  - Vectorizer: `model/vectorizer.pkl`
  - Training data: `model/last_cleaned_training_data.csv`
  - Audit logs: `model/model_audit.json` and `model/model_info.json`
- **Gmail API**: Full message format with headers for classification

---

## Management Commands

### Ingestion
```bash
python manage.py ingest_gmail --days 30
python manage.py ingest_gmail --message-id <msg_id>
python manage.py mark_ghosted
```

### Cleanup
```bash
python manage.py mark_newsletters_ignored --dry-run
python manage.py mark_newsletters_ignored --delete-marked
python manage.py cleanup_newsletters
python manage.py reclassify_messages
```

### Company Management
```bash
python manage.py export_companies
python manage.py import_companies json/companies.json
python manage.py export_labels
```

---

## Security

- **No external data transmission**: All data stays local
- **XSS protection**: All dynamic content escaped
- **Secret scanning**: `detect-secrets` baseline enforcement
- **Admin-only diagnostics**: Environment status restricted
- **API credentials**: Stored in `json/credentials.json` (gitignored)

---

## Classification System

### Label Priority (Highest to Lowest)
1. offer
2. head_hunter
3. noise
4. rejection
5. interview
6. application
7. referral
8. ghosted
9. blank
10. other

### Header Hints
- `is_newsletter`: List-Id, X-Campaign present
- `is_bulk`: Precedence: bulk/list
- `is_automated`: Auto-Submitted header
- `is_noreply`: From contains "noreply"/"no-reply"
- `reply_to`: Reply-To for contact info
- `organization`: Organization header for company extraction
- `auto_submitted`: Auto-Submitted value

### Auto-Ignore Logic
Messages are automatically ignored if:
- `is_newsletter = True`, OR
- `is_bulk = True` AND `is_noreply = True`

---

## Web Routes

- `/` - Dashboard overview
- `/admin/` - Django admin
- `/label-companies/` - Interactive label debugger
- `/company/<id>/` - Company detail with all messages
- `/admin/environment_status/` - System diagnostics

---

## Logging

- **Daily rotation**: `logs/tracker-YYYY-MM-DD.log`
- **Django logs**: `logs/django.log` (rotated at midnight)
- **Retention**: 30 days (configurable via `DJANGO_LOG_BACKUPS`)
- **Debug mode**: Set `DEBUG = True` in parser.py for verbose output

---

## Data Models

### Message
- `msg_id` (PK): Gmail message ID
- `thread_id`: Gmail thread ID
- `subject`, `sender`, `timestamp`
- `ml_label`: ML-predicted label
- `confidence`: ML confidence score
- `company`: FK to Company
- `company_source`: How company was extracted
- `reviewed`: Manual review flag

### ThreadTracking
- `thread_id` (PK): Gmail thread ID
- `company`: FK to Company
- `label`: Classification label
- `application_date`, `rejection_date`, `interview_date`
- `follow_up_dates`: JSON array
- `last_message_date`

### Company
- `name` (unique): Company name
- `domain`: Email domain
- `first_contact`, `last_contact`
- `confidence`: Average ML confidence

### IgnoredMessage
- `msg_id` (PK): Gmail message ID
- `subject`, `sender`, `timestamp`
- `reason`: Why ignored (e.g., "newsletter_headers", "ml_ignore")
- `metadata`: JSON dump of full message metadata

---

## Recent Enhancements

### Newsletter Detection (Nov 2025)
- Header extraction for List-Id, Precedence, X-Campaign, Auto-Submitted
- Auto-ignore before ML classification
- `mark_newsletters_ignored` command for cleanup
- Header text prepended to body for rule pattern matching

### Meeting Detection (Nov 2025)
- Teams/Zoom link detection
- "meeting with" vs "interview with" distinction
- Confidence threshold check (< 0.65 → downgrade to "other")
- Person-name heuristic to reject "Kelly Shaw" as company

### Label Consolidation (Nov 2025)
- Merged "rejected" → "rejection"
- Updated 66 Messages and 2 ThreadTracking entries
- Priority-order debugger with early-exit

### Company Extraction (Nov 2025)
- Organization header fallback
- Person-name filtering with `looks_like_person()`
- Subdomain-aware domain mapping
- Endyna, Sharp Decisions, RAND added to known companies