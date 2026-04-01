# Command Reference

Complete reference for all management commands, scripts, and utilities in GmailJobTracker.

For JavaScript-heavy careers pages and job postings, install the Playwright Chromium browser once per environment:

```bash
python -m playwright install chromium
```

---

## Django Management Commands

All commands are run with: `python manage.py <command> [options]`

### 📧 Ingestion Commands

#### `ingest_gmail`

Fetch and process emails from Gmail API.

```bash
# Ingest last 30 days
python manage.py ingest_gmail --days 30

# Ingest specific message by ID
python manage.py ingest_gmail --message-id 18d4c2f8a1b2c3d4

# Ingest with debug output
DEBUG=1 python manage.py ingest_gmail --days 7
```

**Options**:

- `--days N`: Number of days to fetch (default: 7)
- `--message-id ID`: Re-ingest specific message by Gmail message ID
- Environment variable `DEBUG=1`: Enable verbose logging

**Output**:

- Creates/updates `Message` and `ThreadTracking` records
- Auto-creates `Company` records
- Logs ignored messages to `IgnoredMessage`
- Updates `IngestionStats` daily totals

---

#### `mark_ghosted`

**Manual operation.** Mark companies/applications as "ghosted" when no response after the configured threshold (default 30 days). This command must be run explicitly — it does **not** run automatically on page load.

```bash
# Mark ghosted using default threshold (30 days)
python manage.py mark_ghosted

# Use a custom threshold
python manage.py mark_ghosted --days 45
```

**Logic**:

- Excludes companies already rejected, headhunters, and noise
- Checks `last_message_date` against `GHOSTED_DAYS_THRESHOLD` (AppSetting or env var, default 30)
- Sets `ThreadTracking.status` / `Company.status` to `"ghosted"`
- Sets pre-cutoff `Message.ml_label` to `"ghosted"` for chart visibility
- Logs changes to console

**Options**:

- `--days N`: Override the ghosted threshold for this run (ignores AppSetting/env)

---

#### `update_company_statuses`

**Manual operation.** Bulk-recalculate every company's status based on its latest message label and the configured `GHOSTED_DAYS_THRESHOLD`. Use this after relabeling messages or adjusting the threshold to sync all company statuses at once.

```bash
# Preview changes without writing
python manage.py update_company_statuses --dry-run

# Apply changes
python manage.py update_company_statuses
```

**Logic**:

- Iterates all companies (skips companies with `status="new"`)
- Determines new status from the company's latest `Message.ml_label`:
  - `rejection` → `rejected`
  - `head_hunter` → `headhunter`
  - `interview_invite` → `interview`
  - `job_application` older than threshold → `ghosted`
  - `job_application` within threshold → `application`
- Saves only companies whose status actually changed

**Options**:

- `--dry-run`: Show what would change without making any writes

---

### 🧹 Cleanup Commands

#### `mark_newsletters_ignored` ⭐ **RECOMMENDED**

Re-ingest messages using header analysis to identify and mark newsletters/bulk mail as ignored.

```bash
# Dry run - preview what would be marked
python manage.py mark_newsletters_ignored --dry-run

# Mark as ignored (keeps in Message table for verification)
python manage.py mark_newsletters_ignored

# Mark as ignored AND delete from Message table
python manage.py mark_newsletters_ignored --delete-marked

# Process only last 500 messages
python manage.py mark_newsletters_ignored --limit 500

# Custom batch size for API rate limiting
python manage.py mark_newsletters_ignored --batch-size 25
```

**Options**:

- `--dry-run`: Preview without making changes
- `--delete-marked`: Delete from Message table after marking ignored
- `--limit N`: Only check N most recent messages
- `--batch-size N`: Process N messages per batch (default: 50)

**Logic**:

- Fetches full message with headers from Gmail API
- Extracts `header_hints` (is_newsletter, is_bulk, is_noreply)
- Re-ingests through `ingest_message()` which auto-ignores if newsletter/bulk
- Creates `IgnoredMessage` record with reason="newsletter_headers"
- Optionally deletes from `Message` table

**Output**:

- Shows progress per batch
- Reports: checked count, already ignored, newly ignored, deleted, errors
- Safe to run multiple times (skips already ignored)

---

#### `cleanup_newsletters`

Direct deletion of newsletter/bulk messages (bypasses IgnoredMessage tracking).

```bash
# Dry run - preview deletions
python manage.py cleanup_newsletters --dry-run

# Delete newsletters
python manage.py cleanup_newsletters

# Check only last 1000 messages
python manage.py cleanup_newsletters --limit 1000

# Custom batch size
python manage.py cleanup_newsletters --batch-size 100
```

**Options**:

- `--dry-run`: Preview without deleting
- `--limit N`: Only check N most recent messages
- `--batch-size N`: Gmail API batch size (default: 100)

**Logic**:

- Fetches headers from Gmail API
- Identifies newsletters via `header_hints`
- Directly deletes from `Message` and `ThreadTracking` tables
- Requires confirmation before deletion

**⚠️ Warning**: Use `mark_newsletters_ignored` instead for safer cleanup with audit trail.

---

#### `reclassify_messages`

Re-run classification on existing messages using updated rules/ML.

```bash
python manage.py reclassify_messages
```

**Logic**:

- Iterates all `Message` records
- Re-runs `predict_subject_type()` with current ML model
- Re-runs `rule_label()` with current patterns
- Updates `ml_label` and `confidence`
- Updates `ThreadTracking` labels

**Use Cases**:

- After updating classification rules
- After retraining ML model
- After adding new known companies
- After fixing label priority order

---

### �️ Defense Contract Commands

#### `fetch_contracts`

Fetch and parse defense contract awards from war.gov.

```bash
# Fetch latest 5 articles (default)
python manage.py fetch_contracts

# Fetch up to 10 articles
python manage.py fetch_contracts --max-articles 10

# Re-fetch all articles (bypass cache)
python manage.py fetch_contracts --force-refresh

# Dry run - show article links without saving
python manage.py fetch_contracts --dry-run

# Search existing stored contracts
python manage.py fetch_contracts --search "cybersecurity"
```

**Options**:

- `--max-articles N`: Maximum articles to process (default: 5)
- `--force-refresh`: Re-fetch articles even if already scraped (bypass ScrapedArticle cache)
- `--dry-run`: Show article links without fetching or saving
- `--search QUERY`: Search existing contracts by keyword (does not fetch new data)

**Logic**:

- Uses Playwright (headed Chromium) to bypass Akamai WAF on war.gov
- Fetches the contracts listing page, extracts article links
- For each article: splits text by military branch, parses contract paragraphs
- Extracts: company name, location, dollar amount, contract number, branch, work location
- Links scraped companies to existing `Company` records via fuzzy matching
- Tracks fetched articles in `ScrapedArticle` to skip on subsequent runs

**Output**:

- Creates `DefenseContract` records (deduplicated by source_url + company_name_raw + contract_number)
- Creates `ScrapedArticle` cache entries for processed articles
- Reports: articles processed, contracts created/updated/skipped, errors

---

### �🏢 Company Management Commands

#### `sync_companies` ⭐ **RECOMMENDED AFTER EDITING companies.json**

Synchronize Company database records with companies.json configuration.

```bash
# Preview what would be updated
python manage.py sync_companies --dry-run

# Apply synchronization
python manage.py sync_companies

# Verbose output showing all companies checked
python manage.py sync_companies --verbose
```

**Options**:

- `--dry-run`: Preview without making changes
- `--verbose`: Show all companies checked, not just updates

**Logic**:

- Reads domain_to_company mappings from companies.json
- For each known company, finds matching Company record (by name or alias)
- Updates domain field if empty or different from companies.json
- Reports updates, companies checked, and missing records

**Use Cases**:

- After adding/editing domain_to_company entries
- After adding new companies to known list
- Periodic sync to ensure database matches configuration
- Part of deployment/update workflow

**Output**: Shows which companies were updated and summary statistics

---

#### `export_companies`

Export all companies to JSON file.

```bash
python manage.py export_companies
```

**Output**: `json/companies.json` with structure:

```json
{
  "known_companies": ["Microsoft", "Google", ...],
  "domain_to_company": {
    "microsoft.com": "Microsoft",
    "google.com": "Google"
  },
  "ats_domains": ["greenhouse.io", "lever.co"]
}
```

---

#### `import_companies`

Import companies from JSON file.

```bash
python manage.py import_companies json/companies.json
```

**Logic**:

- Merges with existing companies (no duplicates)
- Updates domain mappings
- Creates `Company` records if missing

---

#### `export_labels`

Export labeled messages for model training review.

```bash
python manage.py export_labels
```

**Output**: CSV with columns:

- `subject`, `body`, `sender`, `ml_label`, `confidence`, `reviewed`

---

## Standalone Scripts

Located in project root or `scripts/` directory.

### `label_companies.py`

Interactive label debugger and company management tool.

```bash
python label_companies.py
```

**Features**:

- View all companies with message counts
- Test rule_label() with custom subjects
- See which rule pattern matched (in priority order)
- Update company names
- Merge duplicate companies

**Web Interface**: Also available at `/label-companies/` route

---

### `check_env.py`

Verify environment setup and dependencies.

```bash
python check_env.py
```

**Checks**:

- Python version
- Required packages installed
- Gmail credentials file exists
- Database file exists and accessible
- Model files present
- Logs directory writable

---

### `train_model.py`

Retrain the message classifier from reviewed messages, with optional explicit CSV imports.

```bash
# Retrain from reviewed data only
python train_model.py --verbose

# Retrain and explicitly include a CSV file as one label
python train_model.py --verbose --csv-path synthetic_data.csv --csv-label noise
```

**Options**:

- `--verbose`: Print label distributions, validation predictions, and effective class weights
- `--csv-path PATH`: Include one CSV file in the current training run
- `--csv-label LABEL`: Label applied to every imported CSV row; required when `--csv-path` is used

**CSV Requirements**:

- Must include a `subject` column, a `body` column, or both
- Blank subject/body rows are ignored during training cleanup
- CSV data is only used when you explicitly pass `--csv-path`; the trainer no longer auto-loads `synthetic_data.csv`

**Admin UI Equivalent**:

- Visit `/reingest_admin/`
- Use **Import a Folder for Model Training** for fixture folders under `tests/emails`
- Optionally enable **Also include a CSV training file** and choose the CSV label before retraining

---

### `scripts/reingest-by-messageID.py`

Re-ingest specific messages by Gmail message ID.

```bash
python scripts/reingest-by-messageID.py <message_id_1> <message_id_2> ...
```

**Use Cases**:

- Test classification changes on specific messages
- Fix incorrectly ingested messages
- Debug parsing issues

---

### `scripts/reclassify_meeting_invites.py`

Find and reclassify meeting invites that were mislabeled as interviews.

```bash
python scripts/reclassify_meeting_invites.py
```

**Logic**:

- Finds `label="interview_invite"` messages
- Checks for Teams/Zoom links + "meeting with" (not "interview")
- Updates label to "other"
- Deletes associated `ThreadTracking`

---

### `scripts/consolidate_rejection_labels.py`

Merge duplicate labels (e.g., "rejected" → "rejection").

```bash
python scripts/consolidate_rejection_labels.py
```

**Logic**:

- Updates `Message.ml_label` and `ThreadTracking.label`
- Updates code constants (`LABEL_MAP`, `_MSG_LABEL_EXCLUDES`)
- Reports total records updated

---

### `scripts/test_rule_label.py`

Test rule-based classification on sample subjects.

```bash
python scripts/test_rule_label.py
```

**Tests**:

- Newsletter keywords → "noise"
- Digest/recommendation → "noise"
- Priority order (offer > rejection > noise)

---

### `scripts/test_predict_fallback.py`

Test ML override logic with rule patterns.

```bash
python scripts/test_predict_fallback.py
```

**Tests**:

- ML predicts "referral" but body has newsletter keyword → "noise"
- ML confidence < 0.85 with noise pattern → "noise" with confidence 1.0

---

### `scripts/check_email_body.py`

Inspect raw email content for debugging.

```bash
python scripts/check_email_body.py <message_id>
```

**Output**:

- Raw body content
- Parsed plain text
- Header extraction results

---

### `scripts/re_enrich_missing_companies.py`

Re-process messages with `company_source="unresolved"`.

```bash
python scripts/re_enrich_missing_companies.py
```

**Logic**:

- Finds messages with no company
- Re-runs company extraction with current logic
- Updates `company` and `company_source`

---

### `scripts/reset_tracker.py`

⚠️ **DESTRUCTIVE**: Reset database for development.

```bash
python scripts/reset_tracker.py
```

**Actions**:

- Deletes all `Message`, `ThreadTracking`, `Company`, `IgnoredMessage` records
- Resets `IngestionStats`
- ⚠️ **No undo** - use only in development

---

### `scripts/scrape_companies.py`

Scrape company information from public sources.

```bash
python scripts/scrape_companies.py
```

**Output**: Company details (name, domain, industry, etc.)

---

## Environment Variables

### `DEBUG`

Enable verbose logging in parser.py.

```bash
# Linux/Mac
export DEBUG=1

# Windows PowerShell
$env:DEBUG=1

# Windows CMD
set DEBUG=1
```

**Output**:

- Classification decisions
- Company extraction steps
- Header analysis results
- Rule pattern matches

---

### `DJANGO_LOG_BACKUPS`

Number of days to retain rotated log files (default: 30).

```bash
export DJANGO_LOG_BACKUPS=60
```

---

## Web Interface Routes

### Dashboard

```
http://localhost:8000/
```

Overview of applications and statistics.

---

### Admin Panel

```
http://localhost:8000/admin/
```

Django admin interface for all models.

---

### Label Companies

```
http://localhost:8000/label-companies/
```

Interactive company labeling with rule debugger.

**Features**:

- View all companies with unlabeled messages
- Test rule patterns with custom subjects
- See priority-order matching
- Update company names in bulk

---

### Company Detail

```
http://localhost:8000/company/<id>/
```

All messages for a specific company.

---

### Environment Status

```
http://localhost:8000/admin/environment_status/
```

System diagnostics (admin-only).

---

### Defense Contract Awards

```
http://localhost:8000/defense_contracts/
```

Searchable listing of defense contract awards scraped from war.gov.

**Features**:

- Search by company name, description, work location
- Filter by military branch (Army, Navy, Air Force, etc.)
- Date range filter (7/14/30/60/90 days or all time)
- Summary stats: total contracts, total value, articles cached
- "Fetch Latest" button for incremental scraping
- "Refresh All" button to re-fetch all articles
- Click company name to view on Label Companies page

---

## Quick Reference

### Daily Workflow

```bash
# 1. Ingest new emails
python manage.py ingest_gmail --days 1

# 2. Mark ghosted applications (manual — run as needed)
python manage.py mark_ghosted

# 3. (Optional) Bulk-sync all company statuses after relabeling
python manage.py update_company_statuses

# 4. Check dashboard
# Visit http://localhost:8000/
```

---

### Initial Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Check environment
python check_env.py

# 3. Run migrations
python manage.py migrate

# 4. Import known companies
python manage.py import_companies json/companies.json

# 5. Initial ingest
python manage.py ingest_gmail --days 90

# 6. Start server
python manage.py runserver
```

---

### After Editing companies.json

```bash
# 1. Validate JSON syntax
python -m json.tool json/companies.json > /dev/null

# 2. Sync database with new mappings
python manage.py sync_companies --dry-run
python manage.py sync_companies

# 3. Re-ingest affected messages (optional)
python manage.py ingest_gmail --message-id <msg_id>
```

---

### Cleanup After Rule Changes

```bash
# 1. Test new rules
python scripts/test_rule_label.py

# 2. Re-classify all messages
python manage.py reclassify_messages

# 3. Clean up newsletters
python manage.py mark_newsletters_ignored --dry-run
python manage.py mark_newsletters_ignored --delete-marked
```

---

### Debugging Classification Issues

```bash
# 1. Enable debug mode
export DEBUG=1

# 2. Re-ingest problem message
python manage.py ingest_gmail --message-id <msg_id>

# 3. Check raw email content
python scripts/check_email_body.py <msg_id>

# 4. Test in label debugger
python label_companies.py
# or visit http://localhost:8000/label-companies/
```

---

## Common Issues

### Newsletter Still Classified as Referral

**Solution**: Re-ingest to use new header extraction

```bash
python manage.py ingest_gmail --message-id <msg_id>
```

### Meeting Invite Labeled as Interview

**Solution**: Run meeting reclassification script

```bash
python scripts/reclassify_meeting_invites.py
```

### Person Name Captured as Company

**Solution**: Add to person-name heuristic or known companies blacklist
Edit `parser.py` → `looks_like_person()` function

### Company Not Extracted

**Solutions**:

1. Add to `json/companies.json` domain mapping
2. Add Organization header fallback
3. Check `company_source` field to see which extraction failed
4. Re-run enrichment: `python scripts/re_enrich_missing_companies.py`

### Duplicate Labels (rejected/rejection)

**Solution**: Run consolidation script

```bash
python scripts/consolidate_rejection_labels.py
```

---

## Performance Tips

### Batch Processing

Use `--batch-size` for large ingestions:

```bash
python manage.py mark_newsletters_ignored --batch-size 25
```

### Limit Scope

Process recent messages first:

```bash
python manage.py mark_newsletters_ignored --limit 1000
```

### Enable Pagination

For large queries, process in chunks:

```python
# In custom scripts
messages = Message.objects.all().iterator(chunk_size=100)
```

---

## Backup & Recovery

### `backup_state`

Create a point-in-time backup bundle for the full local application state.

```bash
# Default backup location under backups/
python manage.py backup_state

# Write to a custom directory
python manage.py backup_state --output-dir ~/Backups/GmailJobTracker

# Keep only the expanded directory and skip the tar.gz archive
python manage.py backup_state --skip-compress
```

**What it captures**:

- PostgreSQL custom dump for `pg_restore`
- Plain SQL dump for `psql`
- PostgreSQL globals when `pg_dumpall` is available
- OAuth credentials and tokens from supported root, `json/`, and `model/` paths when present
- Full `model/` directory
- Full `json/` directory
- `.env` and `.env.local` when present
- Optional `media/` files when present
- Git bundle, tracked source archive, `git status`, `git diff`, dependency snapshot, manifest, and restore notes

**Requirements**:

- `pg_dump` must be installed
- The PostgreSQL client tools must match the database server major version

### `restore_state`

Restore a previously created backup bundle into a local checkout and PostgreSQL database.

```bash
# Restore files and database into the current checkout
python manage.py restore_state backups/gmailjobtracker-backup-YYYYMMDDTHHMMSSZ.tar.gz --force

# Restore into a fresh clone created from the bundled git archive
python manage.py restore_state backups/gmailjobtracker-backup-YYYYMMDDTHHMMSSZ.tar.gz --repo-target-dir ~/restore/GmailJobTracker --restore-globals

# Restore files only
python manage.py restore_state backups/gmailjobtracker-backup-YYYYMMDDTHHMMSSZ.tar.gz --skip-db --project-root /path/to/checkout --force
```

**Options**:

- `--project-root PATH`: Restore files into a specific checkout
- `--repo-target-dir PATH`: Clone the saved git bundle into a fresh directory first
- `--skip-db`: Restore files only
- `--skip-files`: Restore PostgreSQL only
- `--use-plain-sql`: Use the plain SQL dump instead of the custom dump
- `--restore-globals`: Apply PostgreSQL globals when present
- `--force`: Overwrite a dirty checkout or reuse a non-empty target directory

**Requirements**:

- `pg_restore` or `psql` must be installed
- The PostgreSQL client tools must match the database server major version
- Stop the development server and any ingestion job before restoring

### Legacy Manual Backup Database

```bash
# PostgreSQL
PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -U "$DB_USERNAME" "$DB_NAME" > tracker.backup.sql

# Or use Django dumpdata
python manage.py dumpdata > backup.json
```

### Legacy Manual Restore Database

```bash
# PostgreSQL
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USERNAME" -d "$DB_NAME" < tracker.backup.sql

# Or use Django loaddata
python manage.py loaddata backup.json
```

### Export for Migration

```bash
python manage.py export_companies
python manage.py export_labels
```

### 📰 RSS Feed Commands

#### `import_opml`

Import feeds from an OPML subscription file (e.g. from FeedBro).

```bash
# Import default OPML file (feedbro-subscriptions-20260310-110531.opml)
python manage.py import_opml

# Import a custom OPML file
python manage.py import_opml some_other_subscriptions.opml
```

**Function**:

- Reads an OPML file
- Creates `RSSFeed` records for each subscription
- Preserves folder structure as `category`
- Idempotent (safe to re-run, existing feeds skipped)

#### `fetch_rss`

Fetch the latest articles from all active RSS feeds.

```bash
# Fetch latest articles
python manage.py fetch_rss
```

**Function**:

- Iterates all `RSSFeed` where `is_active=True`
- Downloads and parses the feed XML/RSS
- Creates `RSSArticle` records
- Deduplicates based on `link` (GUID)
- Logs errors per feed (continues processing others)
