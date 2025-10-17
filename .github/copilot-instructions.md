# GmailJobTracker - AI Agent Instructions

## Project Overview

**GmailJobTracker** is a privacy-first Django application that ingests Gmail job application emails, extracts structured data using hybrid ML+regex parsing, and provides a dashboard for tracking applications, interviews, and rejections. All data stays local—no external servers.

## Architecture: Big Picture

### Core Components
1. **Gmail Ingestion Pipeline** (`parser.py`, `ingest_gmail.py`)
   - OAuth-authenticated Gmail API pulls messages by label
   - Extracts metadata (subject, body, sender, thread_id) → stores in SQLite
   - Uses `ProcessedMessage` table to track ingestion state and avoid duplicates

2. **Hybrid Entity Extraction** (`parser.py`, `ml_entity_extraction.py`)
   - **Company resolution**: Tiered fallback (known whitelist → domain mapping → ML prediction → body regex)
   - **Message classification**: Rule-based patterns (`patterns.json`) fall back to TfidfVectorizer + LogisticRegression
   - **Status detection**: Keyword matching for interview/rejection/application/noise
   - Confidence thresholds determine if messages auto-mark as `reviewed=True` (85%+ confidence)

3. **Django Models** (`tracker/models.py`)
   - `Company` (canonical, with domain and confidence)
   - `Application` (thread-level, FK to Company, includes ML confidence + manual review flag)
   - `Message` (message-level, FK to Company, stores ML label + body HTML)
   - `UnresolvedCompany`, `IgnoredMessage` for manual review workflows
   - `IngestionStats` tracks daily insert/ignore/skip counts

4. **Dashboard** (`tracker/views.py`, templates)
   - Django admin for labeling + manual company assignment
   - Custom views: company detail (threaded messages), flagged apps (low confidence), alias management
   - Auto-triggers model retraining after labeling via signals (`tracker/signals.py`)

### Data Flow
```
Gmail API → extract_metadata() → parse_subject() → ML classification → ingest_message()
                                                ↓
                              Company resolution (4-tier fallback)
                                                ↓
                        Message/Application ORM create → Stats update
```

## Critical Developer Workflows

### Initial Setup
```powershell
# 1. Install dependencies
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 2. Run environment checks (verifies DB, JSON configs, OAuth, model artifacts)
python check_env.py

# 3. Run migrations
python manage.py migrate

# 4. Configure Gmail OAuth (place credentials.json in json/)
# 5. Set GMAIL_JOBHUNT_LABEL_ID in .env or environment

# 6. Initial ingestion (last 7 days)
python manage.py ingest_gmail --days-back 7

# 7. Start dashboard
python manage.py runserver
```

### Re-ingestion & Re-classification
```powershell
# Re-ingest specific message (updates company/ML label on existing records)
python manage.py ingest_gmail --limit-msg <msg_id>

# Re-classify all messages with updated model
python manage.py reclassify_messages

# Force re-process already-seen messages
python manage.py ingest_gmail --force --days-back 30
```

### Model Training
```powershell
# Train/retrain message classifier (uses labeled data from Message.ml_label)
python train_model.py --verbose

# Artifacts saved to model/:
#   - message_classifier.pkl (LogisticRegression + CalibratedClassifierCV)
#   - subject_vectorizer.pkl / body_vectorizer.pkl (TfidfVectorizer)
#   - message_label_encoder.pkl (sorted list of labels)
```

### Testing
```powershell
pytest                                    # Run all tests
pytest tests/test_ingest_message.py       # Specific test module
pytest --cov=tracker --cov-report=html    # Coverage report
```

## Project-Specific Conventions

### Company Name Resolution (4-Tier Fallback)
1. **Known whitelist**: Normalized match against `companies.json → known` array
2. **Domain mapping**: ATS-aware domain lookup (`companies.json → domain_to_company`)
3. **ML prediction**: `predict_company()` from trained model (fallback if confidence < 60%)
4. **Body regex**: Last resort `@\s*([A-Za-z][\w\s&\-]+)` pattern in email body

**Invalid company filter**: Rejects names matching `patterns.json → invalid_company_prefixes` (e.g., "Resume", "CV", "Gift Card")

### Message Classification Logic
- **ML first**: `predict_subject_type()` combines subject + body TF-IDF features
- **Rule fallback**: If confidence < 0.55, apply `rule_label()` from `patterns.json`
- **Auto-review**: Messages with 85%+ confidence + valid company + non-noise label → `reviewed=True`
- **Ignore threshold**: `noise`, `job_alert`, `head_hunter` labels trigger `IgnoredMessage` logging

### DB Patterns
- **Threading**: `thread_id` from Gmail API groups related messages (e.g., application → response → rejection)
- **Composite index**: `company_job_index = f"{company}::{job_title}::{job_id}"` (normalized, lowercase) for grouping
- **Stats tracking**: `IngestionStats` uses `F()` expressions for atomic increments (`total_inserted=F('total_inserted')+1`)
- **Idempotency**: `ProcessedMessage` table prevents duplicate ingestion; `get_or_create()` used throughout

### Configuration Files (json/)
- **patterns.json**: Regex patterns for classification, domain mappings, ATS domains, invalid prefixes
- **companies.json**: Known companies, domain→company mappings, ATS domains
- **credentials.json**: Gmail OAuth client secrets (gitignored)
- **token.json**: OAuth refresh token (gitignored)

### Django Admin Customizations
- Message inline editing shows thread_id, ML label, confidence, reviewed flag
- Company admin displays message count via `message_count()` method
- Auto-retrain trigger: Saving labeled messages calls `tracker/signals.py → post_save → subprocess.Popen(['python', 'train_model.py'])`

## Integration Points

### Gmail API
- **Auth**: `gmail_auth.py → get_gmail_service()` uses OAuth2 flow, stores token in `json/token.json`
- **Labels**: Filter by `INBOX` + custom label (e.g., `GMAIL_JOBHUNT_LABEL_ID`)
- **Metadata**: Extracts `Subject`, `From`, `Date`, `threadId` from headers
- **Body**: `extract_body_from_parts()` handles multipart MIME, prefers HTML for rich text

### ML Pipeline
- **Training data**: `db.load_training_data()` pulls from `Message` table where `ml_label IS NOT NULL`
- **Weak labeling**: If no human labels exist, bootstraps with regex-based `weak_label()` function
- **Class balancing**: Uses `compute_sample_weight('balanced')` + stratified splits
- **Vectorization**: Separate TF-IDF for subject (10K features, 1-2 grams) and body (40K features, 1-2 grams)
- **Calibration**: Wraps LogisticRegression in `CalibratedClassifierCV(method='isotonic')` for reliable probabilities

### External Dependencies
- **BeautifulSoup4**: HTML stripping for plain-text body extraction
- **spaCy (en_core_web_sm)**: Named entity recognition in `ml_entity_extraction.py`
- **scikit-learn**: TF-IDF, LogisticRegression, calibration
- **detect-secrets**: Pre-commit hook scans for leaked credentials (baseline in `.secrets.baseline`)

## Common Pitfalls & Solutions

### Re-ingestion Not Updating Company
**Problem**: Existing messages skip company enrichment  
**Solution**: `ingest_message()` now updates `existing.company` and `existing.company_source` before early return  
**Location**: `parser.py:752-762` (re-ingest logic block)

### Low Classification Confidence
**Problem**: Generic subjects/bodies yield <50% confidence  
**Solution**: Increase training data via manual labeling in admin, or adjust threshold in `predict_with_fallback()`  
**Location**: `ml_subject_classifier.py:predict_subject_type()` threshold parameter

### Duplicate Threads
**Problem**: Multiple messages in same thread create duplicate Applications  
**Solution**: `Application.thread_id` is unique; `get_or_create()` prevents duplicates  
**Verify**: Check `tracker/models.py:Application` unique constraint

### OAuth Token Expiry
**Problem**: Gmail API returns 401 after long inactivity  
**Solution**: Delete `json/token.json` and re-run ingestion; OAuth flow will refresh  
**Check**: `gmail_auth.py:get_gmail_service()` handles token refresh automatically

## Key Files Reference

| File | Purpose |
|------|---------|
| `parser.py` | Core ingestion logic: metadata extraction, company resolution, message classification |
| `tracker/models.py` | Django ORM models (Company, Application, Message, IngestionStats) |
| `tracker/management/commands/ingest_gmail.py` | Django command for Gmail ingestion (`--days-back`, `--force`, `--limit-msg`) |
| `train_model.py` | ML model training script (loads labeled data, trains classifier, saves to `model/`) |
| `ml_subject_classifier.py` | ML prediction wrapper with rule-based fallback |
| `ml_entity_extraction.py` | spaCy-based company/job title extraction |
| `db_helpers.py` | Utility functions (composite index builder, application lookup) |
| `check_env.py` | Pre-flight checks for required files, migrations, OAuth, secrets baseline |
| `json/patterns.json` | Regex patterns, domain mappings, ATS domains, ignore rules |
| `json/companies.json` | Known companies whitelist, domain→company mappings |

## Security & Privacy

- **Local-only**: All data stored in SQLite (`db/job_tracker.db`), no cloud sync
- **OAuth scopes**: Gmail API limited to read-only message access (`gmail.readonly`)
- **Secret scanning**: `detect-secrets` pre-commit hook prevents credential leaks
- **Input sanitization**: Django ORM escapes SQL; BeautifulSoup strips malicious HTML
- **Admin auth**: Dashboard requires login (`@login_required` decorators)

## Active Development Patterns

### Adding New Message Labels
1. Update `patterns.json → message_labels → <new_label>` with regex patterns
2. Add label to `_MSG_LABEL_PATTERNS` in `parser.py`
3. Retrain model with `python train_model.py`
4. Re-classify existing messages: `python manage.py reclassify_messages`

### Improving Company Resolution
1. Add domain mappings to `companies.json → domain_to_company`
2. Update `KNOWN_COMPANIES` whitelist in `companies.json → known`
3. Re-ingest messages: `python manage.py ingest_gmail --force --days-back 30`

### Custom Dashboard Views
- Follow Django CBV patterns (see `tracker/views.py`)
- Add URL route in `tracker/urls.py`
- Create template in `tracker/templates/tracker/`
- Use `@login_required` decorator for auth

## Migration & Schema Changes

### Adding DB Fields
1. Update `tracker/models.py`
2. Generate migration: `python manage.py makemigrations`
3. Document in `tests/SCHEMA_CHANGELOG.md` (include rollback SQL)
4. Apply: `python manage.py migrate`
5. Backfill historical data if needed (e.g., `scripts/re_enrich_missing_companies.py`)

### Rollback Pattern
- Store rollback SQL in `migrations/<date>_rollback_<change>.txt`
- Example: `rollback_company_job_index.txt` shows how to drop composite index

## Debugging Tips

- **Enable verbose logging**: Set `DEBUG=True` in `parser.py` or `settings.py`
- **Inspect IngestionStats**: Check daily insert/ignore/skip counts via admin or shell
- **Check UnresolvedCompany**: Lists messages where company extraction failed
- **Review IgnoredMessage**: See why messages were filtered (reason column)
- **Test single message**: `python manage.py ingest_gmail --limit-msg <msg_id> --force`

---

**When stuck**: Read `markdown/EXTRACTION_LOGIC.md` for company/job parsing details, `markdown/BACKLOG.md` for planned features, and run `python check_env.py` to verify setup.
