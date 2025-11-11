# GmailJobTracker Dashboard

A local-only Django dashboard for tracking job applications, interviews, and message threads.  
No data leaves your machine. No external servers. Just clean, private job tracking.

## Features

- **Intelligent Classification**: Hybrid ML + rule-based message classification with priority override system
- **Header Analysis**: Automatic detection of newsletters, bulk mail, and automated messages
- **Company Extraction**: Multi-source company resolution (domain mapping, ATS detection, body parsing, Organization headers)
- **Meeting Detection**: Distinguishes actual interviews from general meetings (Teams/Zoom links)
- **Person-Name Filtering**: Prevents person names from being captured as company names
- **Label Management**: Priority-ordered label system with debugger
- **Re-ingestion Safe**: Updates existing messages without duplication

## Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Check environment readiness
python check_env.py

# Visit the admin panel and label messages
# After labeling, the model will retrain automatically and show training output
```

## Management Commands

### 📧 Ingestion & Sync
```bash
# Ingest emails from Gmail
python manage.py ingest_gmail --days 30

# Re-ingest specific message by ID
python manage.py ingest_gmail --message-id <msg_id>

# Mark ghosted applications (no response after 14+ days)
python manage.py mark_ghosted
```

### 🧹 Data Cleanup
```bash
# Find and mark newsletter/bulk mail as ignored (RECOMMENDED)
python manage.py mark_newsletters_ignored --dry-run  # Preview changes
python manage.py mark_newsletters_ignored            # Mark as ignored
python manage.py mark_newsletters_ignored --delete-marked  # Also delete from Message table
python manage.py mark_newsletters_ignored --limit 500     # Check only recent messages

# Direct deletion of newsletter messages (use with caution)
python manage.py cleanup_newsletters --dry-run
python manage.py cleanup_newsletters
python manage.py cleanup_newsletters --limit 500

# Reclassify messages with updated rules
python manage.py reclassify_messages
```

### 🏢 Company Management
```bash
# Export companies to JSON
python manage.py export_companies

# Import companies from JSON
python manage.py import_companies json/companies.json

# Export labels for review
python manage.py export_labels
```

### 🛠️ Utilities & Debugging
```bash
# Interactive label debugger (test rule patterns)
python label_companies.py

# Check environment setup
python check_env.py
```

## Privacy Statement

This tool stores all data locally in db.sqlite3. It does not communicate with any external server.


The application logs to `logs/tracker.log` for custom ingestion/debug messages and standard Django logging outputs to console (or a file in production). Review this file to analyze ingestion steps and classification decisions.
Daily log rotation is enabled:

* Custom ingestion/debug messages: `logs/tracker-YYYY-MM-DD.log` (one file per day, created on first write).
* Django framework logs: `logs/django.log` rotated at midnight retaining recent backups (development) or `/app/logs/django.log` in Docker.

If a legacy `logs/tracker.log` file exists it will stop growing after migration; new entries go to the dated file. You can safely archive or delete the old file.

Retention (production) is controlled via the `DJANGO_LOG_BACKUPS` environment variable (default 30 days). Adjust as needed for disk space and audit requirements.

## Additional Features

- **Environment diagnostics**: `/admin/environment_status/`
- **Secret scanning**: `detect-secrets` baseline enforcement
- **Auto-retraining**: ML model retrains automatically after labeling
- **Label debugger**: `/label-companies/` with priority-order testing
- **Header analysis**: List-Id, Precedence, Auto-Submitted, Organization headers
- **Meeting detection**: Distinguishes interviews from general meetings
- **Person-name filtering**: Prevents capturing person names as companies

## Classification System

### Priority Order (Rules Override ML)
1. **offer** - Job offers
2. **head_hunter** - Recruiter outreach
3. **noise** - Newsletters, bulk mail, automated messages
4. **rejection** - Application rejections
5. **interview** - Interview invitations/confirmations
6. **application** - Application confirmations
7. **referral** - Referral requests
8. **ghosted** - No response after 14+ days
9. **blank** - Unknown/uncategorized
10. **other** - General correspondence

### Header Hints System
The parser extracts and analyzes email headers to improve classification:
- **is_newsletter**: List-Id or X-Campaign headers present
- **is_bulk**: Precedence: bulk or list
- **is_automated**: Auto-Submitted header present
- **is_noreply**: From address contains "noreply" or "no-reply"
- **reply_to**: Reply-To header for contact extraction
- **organization**: Organization header for company fallback
- **auto_submitted**: Value of Auto-Submitted header

### Company Extraction Order
1. Headhunter domain check (highest priority)
2. Domain mapping with subdomain support
3. Indeed job board special case (body extraction)
4. ATS display name (Greenhouse, Lever, etc.)
5. Subject line parsing (various patterns)
6. Body text parsing ("@ symbol", "apply to", etc.)
7. **Organization header fallback** (NEW)
8. Sender name match
9. Unresolved (no company found)

## Web Interface

- **Dashboard**: `/` - Overview of applications and statistics
- **Admin**: `/admin/` - Django admin interface
- **Label Companies**: `/label-companies/` - Interactive company labeling with debugger
- **Company Detail**: `/company/<id>/` - View all messages for a company
- **Environment Status**: `/admin/environment_status/` - System diagnostics
- `urls.py` routing
- Starter templates for metrics + company threads

