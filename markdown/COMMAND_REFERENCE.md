# Command Reference

Complete reference for all management commands, scripts, and utilities in GmailJobTracker.

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

Mark applications as "ghosted" when no response after 14+ days.

```bash
python manage.py mark_ghosted
```

**Logic**:

- Finds `ThreadTracking` with label="application"
- Checks `last_message_date` > 14 days ago
- Updates label to "ghosted"
- Logs changes to console

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

### 🏢 Company Management Commands

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

## Quick Reference

### Daily Workflow

```bash
# 1. Ingest new emails
python manage.py ingest_gmail --days 1

# 2. Mark ghosted applications
python manage.py mark_ghosted

# 3. Check dashboard
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

### Backup Database

```bash
# SQLite
cp job_tracker.db job_tracker.db.backup

# Or use Django dumpdata
python manage.py dumpdata > backup.json
```

### Restore Database

```bash
# SQLite
cp job_tracker.db.backup job_tracker.db

# Or use Django loaddata
python manage.py loaddata backup.json
```

### Export for Migration

```bash
python manage.py export_companies
python manage.py export_labels
```
