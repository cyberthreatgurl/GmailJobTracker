# 🧠 Copilot Instructions: GmailJobTracker

## 📧 Project Overview

**GmailJobTracker** is a privacy-first Django application that transforms Gmail into a job application tracking dashboard using ML + regex-based classification. All data stays local (SQLite), no cloud sync.

### Core Architecture

- **Django 5.2** web framework with SQLite database (`db/job_tracker.db`)
- **Gmail API integration** (read-only OAuth, credentials in `json/credentials.json`)
- **Hybrid ML + Regex classification** for message types (application/rejection/interview/headhunter/noise)
- **Tailwind CSS** for styling (run `python manage.py tailwind start` during development)
- **4-tier company resolution**: whitelist → domain mapping → ATS detection → regex fallback
- **Parser-first design**: `parser.py` orchestrates all email ingestion and classification

---

## 🏗️ Key Architectural Patterns

### Message Processing Pipeline

1. **Gmail API** → `ingest_gmail` management command → `parser.py`
2. **parser.py** extracts metadata, classifies message type, resolves company name
3. Creates/updates Django ORM models: `Message`, `ThreadTracking`, `Company`
4. ML classifier in `ml_subject_classifier.py` provides confidence scores
5. Rule-based patterns from `json/patterns.json` override ML when confidence > 85%

### Configuration-Driven Classification

**Critical JSON files** (never hardcode patterns):
- `json/patterns.json` - Regex patterns for message types, invalid company names, ignore rules
- `json/companies.json` - Known companies, domain→company mappings, ATS domains, aliases
- Auto-reloads when files change (see `DomainMapper.reload_if_needed()`)

### Company Resolution Logic (4 Tiers)

Located in `parser.py` class `CompanyResolver`:

1. **Tier 1**: Whitelist match from `json/companies.json` → `known` array
2. **Tier 2**: Domain mapping via `json/companies.json` → `domain_to_company` dict
3. **Tier 3**: ATS display name extraction (if sender domain in `ats_domains`)
4. **Tier 4**: Subject line regex patterns + validation

See [markdown/EXTRACTION_LOGIC.md](../markdown/EXTRACTION_LOGIC.md) for detailed documentation.

---

## 🐍 Python Code Style (Pylint)

- Use `snake_case` for variables, functions, method names
- Limit line length to 100 characters
- Include docstrings for all public functions/classes
- Use explicit exception types (`except ValueError:` not `except:`)
- Prefer `is`/`is not` for `None` comparisons
- Avoid unused imports and wildcard imports

```python
def fetch_data(source: str) -> dict:
    """Fetches data from the given source."""
    if source is None:
        raise ValueError("Source cannot be None")
    return {"data": source}
```

---

## 🔧 Critical Developer Workflows

### Running Management Commands

All custom commands in `tracker/management/commands/`:

```bash
# Ingest emails from Gmail (primary workflow)
python manage.py ingest_gmail --days 30

# Re-ingest specific message by Gmail ID
python manage.py ingest_gmail --message-id 18d4c2f8a1b2c3d4

# Reclassify all messages (after updating patterns.json)
python manage.py reclassify_messages

# Mark newsletters as ignored (uses header analysis)
python manage.py mark_newsletters_ignored --dry-run

# Sync database with companies.json after manual edits
python manage.py sync_companies

# Update company statuses based on latest message
python manage.py update_company_statuses --dry-run

# Sync ThreadTracking labels with Message labels
python manage.py sync_message_threadtracking_labels --dry-run
```

### Testing

- **Test location**: `tracker/tests/` (configured in `pytest.ini`)
- **Run tests**: `pytest` or `python -m pytest`
- **Coverage**: `pytest --cov=tracker --cov-report=html`
- **Django setup**: Auto-configured in `conftest.py` (`DJANGO_SETTINGS_MODULE=dashboard.settings`)

### Local Development

```bash
# Start Django dev server
python manage.py runserver

# Start Tailwind CSS watcher (in separate terminal)
python manage.py tailwind start

# Train/retrain ML classifier
python train_model.py

# Enable debug logging for parser
DEBUG=1 python manage.py ingest_gmail --days 7
```

---

## 📂 Critical File Reference

| File/Directory | Purpose |
|----------------|---------|
| `parser.py` | **Core ingestion engine** - all email parsing, classification, company resolution |
| `ml_subject_classifier.py` | ML model loader and `predict_subject_type()` function |
| `tracker/models.py` | Django ORM models (15+ models including `Message`, `Company`, `ThreadTracking`) |
| `tracker/views/` | Dashboard views split by domain (companies, messages, applications, admin) |
| `tracker/utils/` | Utility modules (validation.py, email_parsing.py, helpers.py) |
| `json/patterns.json` | Message classification regex patterns and ignore rules |
| `json/companies.json` | Company whitelist, domain mappings, ATS domains |
| `markdown/COMMAND_REFERENCE.md` | Complete command documentation |

---

## 🔗 Integration Points

### Gmail API (`gmail_auth.py`, `authenticate_gmail.py`)

- OAuth flow stored in `token.pickle`
- Credentials in `json/credentials.json`
- Uses `GMAIL_ROOT_FILTER_LABEL` env var to scope ingestion
- Rate limiting: 50 messages per batch (configurable)

### ML Model Training (`train_model.py`)

- Models saved to `model/` directory as `.pkl` files
- Requires labeled training data (export via dashboard)
- TF-IDF vectorizers for subject + body text
- Tracks training runs in `ModelTrainingRun` model

### Dashboard URLs (`tracker/urls.py`)

- `/` - Main dashboard with activity chart and word cloud
- `/label_companies/` - Company management and labeling
- `/label_messages/` - Message review and bulk labeling
- `/job_search_tracker/` - Track companies searched for opportunities
- `/manual_entry/` - Manual entry form for external applications
- `/merge-companies/` - Merge duplicate companies
- `/metrics/` - Statistics and ML model metrics

---

## ⚠️ Common Pitfalls

1. **Never hardcode patterns** - Always use `json/patterns.json` or `json/companies.json`
2. **Check file reloading** - `DomainMapper` auto-reloads companies.json on mtime change
3. **Company sources** - Track via `Message.company_source` (values: `domain_mapping`, `ats_extraction`, `manual`, `eml_import`, etc.)
4. **ATS vs Company domains** - ATS domains (e.g., `myworkdayjobs.com`) serve multiple companies, never map 1:1
5. **Thread vs Message** - `ThreadTracking` groups messages by Gmail thread_id; `Message` is individual email
6. **Company status auto-updates** - Status calculated from latest message label (see `update_company_statuses` command)

---

## 🔍 Finding Your Way Around

**To understand classification logic:**
- Start with `parser.py` → `ingest_message()` function
- Follow to `_classify_and_resolve()` → calls `predict_subject_type()` and `CompanyResolver`

**To add new message patterns:**
- Edit `json/patterns.json` → `message_labels` object
- No code changes needed; parser auto-reloads

**To debug company resolution:**
- Check `json/companies.json` for whitelisted companies and domain mappings
- Review `CompanyResolver` class in `parser.py` for tier logic
- Use `DEBUG=1` env var to see resolution steps

**To modify dashboard views:**
- Views split by domain: `tracker/views/{dashboard,companies,messages,admin}.py`
- Templates in `tracker/templates/tracker/`
- Context processors in `dashboard/context_processors.py`

---

## 📚 Essential Documentation

- **[README.md](../README.md)** - Feature overview and quick start
- **[GETTING_STARTED.md](../GETTING_STARTED.md)** - 15-minute setup guide
- **[markdown/COMMAND_REFERENCE.md](../markdown/COMMAND_REFERENCE.md)** - All management commands
- **[markdown/EXTRACTION_LOGIC.md](../markdown/EXTRACTION_LOGIC.md)** - Company resolution deep dive
- **[markdown/DASHBOARD_OVERVIEW.md](../markdown/DASHBOARD_OVERVIEW.md)** - Dashboard features

---

**Last Updated:** 2026-01-16
